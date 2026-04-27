"""Imagen 4 Ultra tool for Beddel workflows.

Generates images using Google's Imagen 4 Ultra model via Vertex AI
with Application Default Credentials (ADC). No API key needed —
uses ``google-genai`` SDK with ``vertexai=True``.

Prerequisites:
    pip install google-genai Pillow
    gcloud auth application-default login
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any


async def imagen_generate(
    prompt: str,
    aspect_ratio: str = "16:9",
    output_path: str = "/tmp/imagen_output.webp",
    project: str = "beddel-beta",
    location: str = "us-central1",
) -> dict[str, Any]:
    """Generate an image with Imagen 4 Ultra via Vertex AI ADC.

    Args:
        prompt: Text prompt describing the desired image.
        aspect_ratio: One of 1:1, 3:4, 4:3, 9:16, 16:9.
        output_path: File path to save the result (.webp).
        project: GCP project ID.
        location: GCP region.

    Returns:
        Dict with status, output_path, and file size.
    """
    from google import genai
    from google.genai import types
    from PIL import Image

    # Initialize with Vertex AI + ADC (no API key)
    client = genai.Client(vertexai=True, project=project, location=location)

    # Generate with Imagen 4 Ultra
    result = client.models.generate_images(
        model="imagen-4.0-ultra-generate-001",
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            safety_filter_level="BLOCK_ONLY_HIGH",
            person_generation="DONT_ALLOW",
        ),
    )

    if not result.generated_images:
        return {
            "status": "error",
            "message": "No images generated — prompt may have been filtered.",
        }

    # Decode and save as optimized webp
    raw_bytes = result.generated_images[0].image.image_bytes
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), "WEBP", quality=85, method=6)

    size_kb = out.stat().st_size / 1024

    return {
        "status": "success",
        "message": f"Image saved to {out} ({size_kb:.0f} KB, {img.size[0]}x{img.size[1]})",
        "output_path": str(out),
        "width": img.size[0],
        "height": img.size[1],
        "size_kb": round(size_kb),
        "model": "imagen-4.0-ultra-generate-001",
        "auth": "vertex-ai-adc",
    }
