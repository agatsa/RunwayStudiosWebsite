# services/agent_swarm/creative/video_gen.py
"""
Video generation for UGC ad creatives.

Two generation modes:
  1. generate_ugc_heygen()          — HeyGen API: AI avatar reads a UGC script
  2. generate_lifestyle_video_kling() — fal.ai Kling: animate product photo into lifestyle clip
"""
import os
import time
import requests
import fal_client

from services.agent_swarm.config import HEYGEN_API_KEY, FAL_KEY

HEYGEN_BASE = "https://api.heygen.com"


# ── HeyGen helpers ──────────────────────────────────────────

def _heygen_headers() -> dict:
    return {
        "X-Api-Key": HEYGEN_API_KEY,
        "Content-Type": "application/json",
    }


def list_heygen_avatars() -> list[dict]:
    """Return available HeyGen avatars: [{avatar_id, name, preview_image_url}]"""
    r = requests.get(f"{HEYGEN_BASE}/v2/avatars", headers=_heygen_headers(), timeout=15)
    r.raise_for_status()
    data = r.json().get("data", {})
    avatars = data.get("avatars", [])
    return [
        {
            "avatar_id": a.get("avatar_id"),
            "name": a.get("avatar_name", ""),
            "preview_url": a.get("preview_image_url", ""),
            "gender": a.get("gender", ""),
        }
        for a in avatars
    ]


def list_heygen_voices(language: str = "en") -> list[dict]:
    """Return available HeyGen voices filtered by language prefix."""
    r = requests.get(f"{HEYGEN_BASE}/v2/voices", headers=_heygen_headers(), timeout=15)
    r.raise_for_status()
    voices = r.json().get("data", {}).get("voices", [])
    filtered = [
        {
            "voice_id": v.get("voice_id"),
            "name": v.get("display_name", ""),
            "language": v.get("language", ""),
            "gender": v.get("gender", ""),
        }
        for v in voices
        if (v.get("language") or "").startswith(language)
    ]
    return filtered


def get_default_heygen_avatar() -> tuple[str, str]:
    """
    Pick a good default avatar + English voice.
    Prefers Indian English (en-IN) voice. Falls back to first available.
    Returns (avatar_id, voice_id).
    """
    try:
        avatars = list_heygen_avatars()
        voices = list_heygen_voices("en")

        # Prefer en-IN voice; fall back to any English
        en_in = [v for v in voices if "IN" in v.get("language", "")]
        chosen_voice = (en_in or voices or [{}])[0].get("voice_id", "")

        # Pick first available avatar
        chosen_avatar = (avatars or [{}])[0].get("avatar_id", "")

        print(f"HeyGen default: avatar={chosen_avatar}, voice={chosen_voice}")
        return chosen_avatar, chosen_voice

    except Exception as e:
        print(f"get_default_heygen_avatar error: {e}")
        return "", ""


def generate_ugc_heygen(
    script: str,
    avatar_id: str,
    voice_id: str,
    aspect_ratio: str = "9:16",
    poll_interval: int = 10,
    max_wait: int = 600,
    product_image_url: str = None,
) -> str:
    """
    Submit a HeyGen video generation job, poll until complete, return video URL.

    aspect_ratio: "9:16" for Stories/Reels, "16:9" for Feed video
    poll_interval: seconds between status checks
    max_wait: maximum total seconds to wait (default 10 min)
    product_image_url: if provided, used as background so avatar appears in front of product

    Raises RuntimeError on failure or timeout.
    """
    if not HEYGEN_API_KEY:
        raise RuntimeError("HEYGEN_API_KEY not configured")

    # Dimension based on aspect ratio
    if aspect_ratio == "9:16":
        width, height = 720, 1280
    elif aspect_ratio == "1:1":
        width, height = 1080, 1080
    else:  # 16:9 default
        width, height = 1280, 720

    # Use product image as background if available — avatar appears in front of product
    if product_image_url:
        background = {"type": "image", "url": product_image_url}
    else:
        background = {"type": "color", "value": "#f5f5f5"}

    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "text",
                    "input_text": script,
                    "voice_id": voice_id,
                    "speed": 1.0,
                },
                "background": background,
            }
        ],
        "dimension": {"width": width, "height": height},
        "test": False,
    }

    # Submit generation job
    r = requests.post(
        f"{HEYGEN_BASE}/v2/video/generate",
        headers=_heygen_headers(),
        json=payload,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"HeyGen generate failed: {r.status_code} {r.text[:300]}")

    video_id = r.json().get("data", {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"HeyGen returned no video_id: {r.text[:300]}")

    print(f"HeyGen job submitted: video_id={video_id}")

    # Poll for completion
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        status_r = requests.get(
            f"{HEYGEN_BASE}/v1/video_status.get",
            headers=_heygen_headers(),
            params={"video_id": video_id},
            timeout=15,
        )
        if not status_r.ok:
            print(f"HeyGen status check failed ({elapsed}s): {status_r.status_code}")
            continue

        status_data = status_r.json().get("data", {})
        status = status_data.get("status", "")
        print(f"HeyGen status ({elapsed}s): {status}")

        if status == "completed":
            video_url = status_data.get("video_url") or status_data.get("video_url_caption")
            if not video_url:
                raise RuntimeError(f"HeyGen completed but no video_url in response: {status_data}")
            print(f"HeyGen video ready: {video_url}")
            return video_url

        if status in ("failed", "error"):
            error = status_data.get("error", "unknown error")
            raise RuntimeError(f"HeyGen video generation failed: {error}")

    raise RuntimeError(f"HeyGen video timed out after {max_wait}s (video_id={video_id})")


# ── fal.ai Runway Gen-3 Turbo lifestyle video ────────────────

def generate_lifestyle_video_kling(
    product_image_url: str,
    scene_prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
) -> str:
    """
    Animate a product photo into a lifestyle video using Runway Gen-3 Turbo.
    Runway is significantly better than Kling at maintaining product shape/color fidelity.
    Returns public MP4 video URL.

    product_image_url: CDN URL of the uploaded product photo
    scene_prompt: describes the scene/motion to generate
    duration: 5 or 10 seconds
    aspect_ratio: "9:16" for Stories/Reels, "16:9" for Feed
    """
    os.environ["FAL_KEY"] = FAL_KEY

    # Runway Gen-3 uses "ratio" not "aspect_ratio", with pixel dimensions
    ratio_map = {
        "9:16": "768:1280",
        "16:9": "1280:768",
        "1:1":  "1280:1280",
    }
    ratio = ratio_map.get(aspect_ratio, "768:1280")

    result = fal_client.run(
        "fal-ai/runway-gen3/turbo/image-to-video",
        arguments={
            "image_url": product_image_url,
            "prompt": scene_prompt,
            "duration": duration,
            "ratio": ratio,
        },
    )

    # Runway returns {"video": {"url": "..."}}
    video = result.get("video", {})
    if isinstance(video, dict):
        url = video.get("url")
    elif isinstance(video, list) and video:
        url = video[0].get("url") if isinstance(video[0], dict) else video[0]
    else:
        url = None

    if not url:
        raise RuntimeError(f"Runway Gen-3 returned no video URL. Response: {result}")

    print(f"Runway Gen-3 video ready: {url}")
    return url
