# services/agent_swarm/creative/image_gen.py
"""
fal.ai image generation for ad creatives.

Three generation modes:
  1. generate_ad_image()        — Standard T2I (Flux Pro) or basic img2img
  2. generate_ad_image_ip_adapter() — IP-Adapter: preserves product identity from reference photo
  3. generate_ad_image_virtual_tryon() — LEFFA two-step: generate base person → try-on product
"""
import os
import fal_client

from services.agent_swarm.config import FAL_KEY


def generate_ad_image(
    prompt: str,
    size: str = "square_hd",
    reference_image_url: str = None,
    strength: float = 0.85,
) -> str:
    """
    Generate an ad image using fal.ai.
    Returns the public image URL.

    size options: "square_hd" (1024x1024), "portrait_4_3" (1024x1365),
                  "portrait_16_9" (576x1024 — Stories)

    If reference_image_url is provided, uses img2img (Flux Dev image-to-image).
    strength: how much to change the image (0.0 = barely change, 1.0 = full regeneration).
    """
    os.environ["FAL_KEY"] = FAL_KEY

    if reference_image_url:
        # Image-to-image: use user's reference photo as base, generate inspired by prompt
        result = fal_client.run(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "prompt": prompt,
                "image_url": reference_image_url,
                "strength": strength,
                "image_size": size,
                "num_images": 1,
                "output_format": "jpeg",
            },
        )
    else:
        # Standard text-to-image
        result = fal_client.run(
            "fal-ai/flux-pro/v1.1",
            arguments={
                "prompt": prompt,
                "image_size": size,
                "num_images": 1,
                "safety_tolerance": "2",
                "output_format": "jpeg",
            },
        )

    images = result.get("images", [])
    if not images:
        raise RuntimeError(f"fal.ai returned no images. Response: {result}")

    url = images[0].get("url", "")
    if not url:
        raise RuntimeError(f"fal.ai returned image with no URL. Response: {result}")
    return url


def generate_ad_image_ip_adapter(
    prompt: str,
    product_image_url: str,
    ip_scale: float = 0.8,
    size: str = "square_hd",
) -> str:
    """
    Generate ad image with product identity preserved via IP-Adapter.

    IP-Adapter extracts visual features (shape, color, texture) from the product
    reference image and injects them into generation — much better fidelity than
    standard img2img which just pixel-blends.

    ip_scale: 0-1. Higher = product features dominate (0.8 recommended for wearables).
    """
    os.environ["FAL_KEY"] = FAL_KEY

    result = fal_client.run(
        "fal-ai/flux-ip-adapter",
        arguments={
            "prompt": prompt,
            "ip_adapter_image_url": product_image_url,
            "ip_adapter_scale": ip_scale,
            "image_size": size,
            "num_images": 1,
            "output_format": "jpeg",
        },
    )

    images = result.get("images", [])
    if not images:
        raise RuntimeError(f"fal.ai IP-Adapter returned no images. Response: {result}")

    url = images[0].get("url", "")
    if not url:
        raise RuntimeError(f"fal.ai IP-Adapter returned image with no URL. Response: {result}")
    return url


def generate_ad_image_virtual_tryon(
    garment_image_url: str,
    base_scene_prompt: str,
    size: str = "square_hd",
) -> str:
    """
    Two-step pipeline for clothing items:
      Step 1: Generate a base person image (no product/garment) from text prompt.
      Step 2: LEFFA virtual try-on — places the garment exactly onto the person.

    Returns final image URL with product correctly placed on person.
    """
    os.environ["FAL_KEY"] = FAL_KEY

    # Step 1: Generate base person scene (no garment)
    result1 = fal_client.run(
        "fal-ai/flux-pro/v1.1",
        arguments={
            "prompt": base_scene_prompt,
            "image_size": size,
            "num_images": 1,
            "safety_tolerance": "2",
            "output_format": "jpeg",
        },
    )
    images1 = result1.get("images", [])
    if not images1:
        raise RuntimeError(f"Step 1 (base scene) returned no images. Response: {result1}")
    base_image_url = images1[0].get("url", "")
    if not base_image_url:
        raise RuntimeError(f"Step 1 (base scene) returned image with no URL. Response: {result1}")

    # Step 2: Virtual try-on — place product on person
    result2 = fal_client.run(
        "fal-ai/leffa",
        arguments={
            "model_type": "virtual_tryon",
            "human_image_url": base_image_url,
            "garment_image_url": garment_image_url,
        },
    )
    images2 = result2.get("images", [])
    if not images2:
        raise RuntimeError(f"Step 2 (virtual try-on) returned no images. Response: {result2}")

    url = images2[0].get("url", "")
    if not url:
        raise RuntimeError(f"Step 2 (virtual try-on) returned image with no URL. Response: {result2}")
    return url


def generate_product_variations(
    product_image_url: str,
    product_description: str,
    count: int = 8,
) -> list[str]:
    """
    Generate multiple AI copies of a product image for LoRA training.

    Uses img2img at very low strength (0.15) to preserve the product's exact
    appearance while creating slight variation in angle, lighting, background.
    This gives LoRA training enough visual diversity without needing multiple
    real photos from the user.

    Returns list of generated image URLs (may be fewer than count on errors).
    """
    os.environ["FAL_KEY"] = FAL_KEY

    variation_prompts = [
        f"clean product photo, {product_description}, pure white background, slight left angle",
        f"clean product photo, {product_description}, pure white background, slight right angle",
        f"clean product photo, {product_description}, studio lighting, top-down view",
        f"clean product photo, {product_description}, natural window lighting, front view",
        f"clean product photo, {product_description}, dark gradient background, front view",
        f"clean product photo, {product_description}, soft studio light, 3/4 angle view",
        f"clean product photo, {product_description}, light grey background, slightly tilted",
        f"clean product photo, {product_description}, close-up detail shot, white background",
    ]

    urls = []
    for prompt in variation_prompts[:count]:
        try:
            result = fal_client.run(
                "fal-ai/flux/dev/image-to-image",
                arguments={
                    "prompt": prompt,
                    "image_url": product_image_url,
                    "strength": 0.15,  # Very low — preserve product appearance exactly
                    "image_size": "square_hd",
                    "num_images": 1,
                    "output_format": "jpeg",
                },
            )
            images = result.get("images", [])
            if images:
                img_url = images[0].get("url", "")
                if img_url:
                    urls.append(img_url)
        except Exception as e:
            print(f"Variation generation failed for prompt '{prompt[:60]}': {e}")

    return urls


def generate_ad_image_openai(
    prompt: str,
    product_image_url: str = None,
    size: str = "1024x1024",
) -> str:
    """
    Generate an ad image using OpenAI gpt-image-1.

    If product_image_url is provided, uses images.edit() with the product photo
    as a visual reference — the model composes an ad scene featuring that product.
    Falls back to images.generate() if edit() fails or no product image is given.

    gpt-image-1 always returns b64_json — decoded bytes are uploaded to GCS
    and a public URL is returned.

    size: "1024x1024" (square) | "1024x1792" (portrait 9:16) | "1792x1024" (landscape)
    """
    import base64
    import uuid as _uuid
    from io import BytesIO

    import requests as _requests
    from openai import OpenAI
    from google.cloud import storage as gcs

    from services.agent_swarm.config import OPENAI_API_KEY

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=OPENAI_API_KEY)
    img_b64 = None

    if product_image_url:
        try:
            r = _requests.get(product_image_url, timeout=30)
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "image/jpeg")
            img_buf = BytesIO(r.content)
            fname = "product.png" if "png" in content_type else "product.jpg"

            # Augment prompt so the model understands this is a product reference
            edit_prompt = (
                f"{prompt}. "
                "Feature the provided product prominently in the scene. "
                "No text overlays. Photorealistic, professional ad photography."
            )
            response = client.images.edit(
                model="gpt-image-1",
                image=(fname, img_buf, content_type),
                prompt=edit_prompt,
                size=size,
            )
            img_b64 = response.data[0].b64_json
        except Exception as e:
            print(f"gpt-image-1 images.edit() failed: {e} — falling back to generate()")
            img_b64 = None

    if img_b64 is None:
        # Text-to-image fallback (or when no product image provided)
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size,
        )
        img_b64 = response.data[0].b64_json

    # Decode base64 → upload to GCS → return public URL
    img_data = base64.b64decode(img_b64)
    filename = f"generated-ads/{_uuid.uuid4().hex}.png"
    bucket_name = "wa-agency-raw-wa-ai-agency"

    _gcs = gcs.Client()
    bucket = _gcs.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_string(img_data, content_type="image/png")

    return f"https://storage.googleapis.com/{bucket_name}/{filename}"


def generate_ad_image_lora(
    prompt: str,
    lora_url: str,
    trigger_word: str,
    lora_scale: float = 1.0,
    size: str = "square_hd",
) -> str:
    """
    Generate ad image using a fine-tuned LoRA model trained on the product photos.

    This gives the highest possible product fidelity — the model has literally
    been trained on the exact product and remembers every detail.

    trigger_word must be prepended to the prompt so the LoRA activates.
    lora_scale: 0-1 (1.0 = full LoRA strength recommended for product consistency).
    """
    os.environ["FAL_KEY"] = FAL_KEY

    # Prepend trigger word to activate LoRA
    full_prompt = f"{trigger_word} {prompt}"

    result = fal_client.run(
        "fal-ai/flux-lora",
        arguments={
            "prompt": full_prompt,
            "loras": [{"path": lora_url, "scale": lora_scale}],
            "image_size": size,
            "num_images": 1,
            "output_format": "jpeg",
            "safety_tolerance": "2",
        },
    )

    images = result.get("images", [])
    if not images:
        raise RuntimeError(f"fal.ai LoRA generation returned no images. Response: {result}")

    url = images[0].get("url", "")
    if not url:
        raise RuntimeError(f"fal.ai LoRA returned image with no URL. Response: {result}")
    return url
