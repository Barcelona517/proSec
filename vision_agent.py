from __future__ import annotations

from pathlib import Path
import base64
from html import escape
import json
import mimetypes
import re
from typing import Any

from config import MODEL_NAME, VISION_MODEL
from llm_client import build_client, build_vision_client


def _image_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise RuntimeError(f"图片不存在: {image_path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "image/png"

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _extract_json_block(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}

    candidates = [raw]
    fence = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fence:
        candidates.append(fence.group(1))
    brace = re.search(r"(\{.*\})", raw, flags=re.S)
    if brace:
        candidates.append(brace.group(1))

    for item in candidates:
        try:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}


def _extract_problem_from_image(user_input: str, image_path: str) -> dict[str, Any]:
    client = build_vision_client()
    data_url = _image_to_data_url(image_path)
    prompt = (user_input or "").strip() or "请识别这张题目图片。"

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是中文视觉识别助手。你的任务不是解题，而是尽量准确识别图片中的题目内容。"
                    "请只输出一个 JSON 对象，不要输出额外解释。"
                    "字段固定为："
                    "is_problem(boolean), "
                    "subject(string), "
                    "question_text(string), "
                    "recognized_text(string), "
                    "conditions(array of string), "
                    "formulas(array of string), "
                    "figure_description(string), "
                    "uncertain_points(array of string)."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        temperature=0.1,
    )

    raw = (response.choices[0].message.content or "").strip()
    parsed = _extract_json_block(raw)
    if parsed:
        parsed["_raw_model_output"] = raw
        return parsed

    return {
        "is_problem": True,
        "subject": "",
        "question_text": "",
        "recognized_text": raw,
        "conditions": [],
        "formulas": [],
        "figure_description": "",
        "uncertain_points": ["视觉模型没有按要求返回 JSON，已改用原始识别文本。"],
        "_raw_model_output": raw,
    }


def _solve_problem_with_text_model(user_input: str, extracted: dict[str, Any]) -> str:
    client = build_client()
    question_text = str(extracted.get("question_text", "") or "").strip()
    recognized_text = str(extracted.get("recognized_text", "") or "").strip()

    if not question_text and not recognized_text:
        return "图片里没有识别出足够清晰的题目内容，请换一张更清晰的图片，或者手动补充题目文字。"

    solve_request = (user_input or "").strip() or "请详细解答这道题。"
    payload = {
        "subject": str(extracted.get("subject", "") or "").strip(),
        "question_text": question_text,
        "recognized_text": recognized_text,
        "conditions": extracted.get("conditions", []) if isinstance(extracted.get("conditions", []), list) else [],
        "formulas": extracted.get("formulas", []) if isinstance(extracted.get("formulas", []), list) else [],
        "figure_description": str(extracted.get("figure_description", "") or "").strip(),
        "uncertain_points": extracted.get("uncertain_points", []) if isinstance(extracted.get("uncertain_points", []), list) else [],
    }

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个擅长中文解题的推理助手。"
                    "视觉模型已经先识别了图片内容，你现在不要再猜图，而是基于给定结构化信息解题。"
                    "如果识别结果存在不确定点，要先提示，再给出最合理的解法。"
                    "输出尽量包含：题目整理、解题思路、详细步骤、最终答案。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户要求：{solve_request}\n\n"
                    "下面是视觉模型识别出的题目信息（JSON）：\n"
                    f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        temperature=0.2,
    )
    answer = (response.choices[0].message.content or "").strip()
    return answer or "解题模型没有返回内容，请稍后重试。"


def _infer_image_intent_mode(user_input: str, extracted: dict[str, Any]) -> str:
    text = (user_input or "").strip().lower()
    solve_hints = [
        "解",
        "解题",
        "求",
        "证明",
        "计算",
        "怎么做",
        "怎么证",
        "答案",
        "步骤",
        "solve",
        "answer",
        "proof",
        "calculate",
    ]
    recognize_hints = [
        "识别",
        "ocr",
        "描述",
        "看看图里",
        "图片里有什么",
        "提取文字",
        "recognize",
        "describe",
    ]
    if any(hint in text for hint in solve_hints):
        return "solve"
    if any(hint in text for hint in recognize_hints):
        return "recognize"

    question_text = str(extracted.get("question_text", "") or "").strip()
    recognized_text = str(extracted.get("recognized_text", "") or "").strip()
    subject = str(extracted.get("subject", "") or "").strip().lower()
    combined = question_text or recognized_text
    if subject in {"math", "数学", "physics", "物理", "chemistry", "化学"}:
        return "solve"
    if re.search(r"[?？]|求|证明|已知|设|计算|解方程", combined):
        return "solve"
    return "recognize"


def _format_extraction_markdown(extracted: dict[str, Any]) -> str:
    lines: list[str] = []

    subject = str(extracted.get("subject", "") or "").strip()
    if subject:
        lines.append(f"学科：{escape(subject)}")

    question_text = str(extracted.get("question_text", "") or "").strip()
    if question_text:
        lines.append(f"题目：{escape(question_text)}")

    figure_description = str(extracted.get("figure_description", "") or "").strip()
    if figure_description:
        lines.append(f"图形/图片说明：{escape(figure_description)}")

    conditions = extracted.get("conditions", [])
    if isinstance(conditions, list):
        clean = [str(x).strip() for x in conditions if str(x).strip()]
        if clean:
            lines.append("已知条件：")
            lines.extend([f"- {escape(item)}" for item in clean[:8]])

    formulas = extracted.get("formulas", [])
    if isinstance(formulas, list):
        clean = [str(x).strip() for x in formulas if str(x).strip()]
        if clean:
            lines.append("识别到的公式：")
            lines.extend([f"- {escape(item)}" for item in clean[:8]])

    uncertain = extracted.get("uncertain_points", [])
    if isinstance(uncertain, list):
        clean = [str(x).strip() for x in uncertain if str(x).strip()]
        if clean:
            lines.append("识别提醒：")
            lines.extend([f"- {escape(item)}" for item in clean[:6]])

    recognized_text = str(extracted.get("recognized_text", "") or "").strip()
    if recognized_text and not question_text:
        short_text = recognized_text[:700]
        if len(recognized_text) > 700:
            short_text += "..."
        lines.append("原始识别文本：")
        lines.append(escape(short_text))

    content = "<br>".join(line.replace("\n", "<br>") for line in lines if line)
    if not content:
        content = "没有提取到可展示的识别摘要。"
    return (
        "<details class='vision-card'>"
        "<summary>视觉识别结果</summary>"
        f"<div class='vision-card-body'>{content}</div>"
        "</details>"
    )


def analyze_image_with_optional_solving(user_input: str, image_path: str, mode: str = "auto") -> dict[str, Any]:
    extracted = _extract_problem_from_image(user_input, image_path)
    extraction_md = _format_extraction_markdown(extracted)
    resolved_mode = mode if mode in {"recognize", "solve"} else _infer_image_intent_mode(user_input, extracted)

    if resolved_mode == "recognize":
        return {
            "mode": "recognize",
            "extracted": extracted,
            "recognition_markdown": extraction_md,
            "answer": extraction_md,
        }

    solved = _solve_problem_with_text_model(user_input, extracted)
    final_text = extraction_md + "\n\n---\n\n### 解题结果\n" + solved
    return {
        "mode": "solve",
        "extracted": extracted,
        "recognition_markdown": extraction_md,
        "answer": final_text,
    }


def run_vision_agent(user_input: str, image_path: str, mode: str = "auto") -> str:
    result = analyze_image_with_optional_solving(user_input, image_path, mode=mode)
    return str(result.get("answer", "") or "")
