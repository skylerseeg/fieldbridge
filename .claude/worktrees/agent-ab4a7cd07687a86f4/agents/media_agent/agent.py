"""
Media Library Agent
AI tagging and natural language search for VanCon's photo/video library.
Uses Claude Vision for image analysis and tagging.
"""
import anthropic
import base64
from pathlib import Path

client = anthropic.Anthropic()

def tag_image(image_path: str) -> dict:
    """
    Send image to Claude Vision → return structured tags.
    Tags: project_type, equipment_visible, work_phase, location_type,
          quality_score, suggested_caption, vista_job_number (if detectable)
    """
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    ext = Path(image_path).suffix.lower()
    media_type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".png": "image/png", ".webp": "image/webp"}
    media_type = media_type_map.get(ext, "image/jpeg")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                    "media_type": media_type, "data": image_data}},
                {"type": "text", "text": (
                    "Analyze this construction photo and return ONLY a JSON object with: "
                    "{project_type, equipment_visible: [], work_phase, location_type, "
                    "quality_score (1-10), suggested_caption, keywords: []}"
                )},
            ],
        }],
    )
    import json, re
    text = response.content[0].text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(match.group(0)) if match else {}
