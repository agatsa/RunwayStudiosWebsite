# services/agent_swarm/wa.py  — WhatsApp send helper
import requests
from services.agent_swarm.config import WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, META_API_VERSION


def send_text(to: str, text: str, tenant: dict = None) -> bool:
    t = tenant or {}
    tenant_token = t.get("meta_access_token")
    token = tenant_token or WA_ACCESS_TOKEN
    # Only use tenant's phone_id if they have their own token; else send from agency default
    phone_id = (t.get("wa_phone_number_id") if tenant_token else None) or WA_PHONE_NUMBER_ID
    if not token or not phone_id:
        print("❌ WA_ACCESS_TOKEN or WA_PHONE_NUMBER_ID missing")
        return False
    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:3900]},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    print(f"WA SEND → {to} | status={r.status_code}")
    return r.status_code < 300


def send_video(to: str, video_url: str, caption: str = "", tenant: dict = None) -> bool:
    """Send a video via WhatsApp using a public MP4 URL."""
    t = tenant or {}
    tenant_token = t.get("meta_access_token")
    token = tenant_token or WA_ACCESS_TOKEN
    phone_id = (t.get("wa_phone_number_id") if tenant_token else None) or WA_PHONE_NUMBER_ID
    if not token or not phone_id:
        print("❌ WA_ACCESS_TOKEN or WA_PHONE_NUMBER_ID missing")
        return False
    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "video",
        "video": {
            "link": video_url,
            "caption": caption[:1000],
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    print(f"WA VIDEO SEND → {to} | status={r.status_code}")
    if not r.ok:
        print(f"WA VIDEO ERROR: {r.text[:300]}")
    return r.status_code < 300


def send_image(to: str, image_url: str, caption: str = "", tenant: dict = None) -> bool:
    """Send an image via WhatsApp using a public URL."""
    t = tenant or {}
    tenant_token = t.get("meta_access_token")
    token = tenant_token or WA_ACCESS_TOKEN
    phone_id = (t.get("wa_phone_number_id") if tenant_token else None) or WA_PHONE_NUMBER_ID
    if not token or not phone_id:
        print("❌ WA_ACCESS_TOKEN or WA_PHONE_NUMBER_ID missing")
        return False
    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption[:3000],
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"WA IMAGE SEND → {to} | status={r.status_code}")
    if not r.ok:
        print(f"WA IMAGE ERROR: {r.text[:300]}")
    return r.status_code < 300
