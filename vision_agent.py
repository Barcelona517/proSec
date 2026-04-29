from __future__ import annotations

from pathlib import Path
import base64
import mimetypes

from config import VISION_MODEL
from llm_client import build_vision_client


def _image_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise RuntimeError(f"图片不存在: {image_path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "image/png"

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def run_vision_agent(user_input: str, image_path: str) -> str:
    prompt = (user_input or "").strip() or "请识别这张图片的内容，并给出清晰说明。"
    client = build_vision_client()
    data_url = _image_to_data_url(image_path)

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一个擅长看图识别、读题、讲解的中文助手。直接回答用户问题。",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()
