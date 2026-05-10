from __future__ import annotations

from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import socket
import urllib.parse
from uuid import uuid4
from typing import Any

import gradio as gr

from config import HISTORY_FILE, MODEL_NAME, VISION_MODEL, WORKSPACE_ROOT
from main import load_history, run_agent_stream_with_trace, run_agent_with_trace, save_history
from tooling import ToolRegistry
from vision_agent import run_vision_agent


os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

CONVERSATIONS_FILE = WORKSPACE_ROOT / "conversations.json"
UPLOADS_DIR = WORKSPACE_ROOT / "uploads"
READABLE_FILE_TYPES = {
    ".txt",
    ".md",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _make_title_from_messages(messages: list[dict]) -> str:
    for item in messages:
        if item.get("role") != "user":
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        cleaned = re.sub(r"[\r\n]+", " ", content)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.!?;:，。！；")
        return cleaned[:18] + ("..." if len(cleaned) > 18 else "")
    return "新对话"


def _normalize_conversation(conv: dict) -> dict:
    return {
        "id": str(conv.get("id") or uuid4()),
        "title": str(conv.get("title") or "新对话"),
        "updated_at": str(conv.get("updated_at") or _now_iso()),
        "messages": list(conv.get("messages") or []),
        "pinned": bool(conv.get("pinned", False)),
    }


def _conversation_has_messages(conv: dict) -> bool:
    messages = conv.get("messages", [])
    return isinstance(messages, list) and any(bool(str(item.get("content", "")).strip()) for item in messages if isinstance(item, dict))


def _new_conversation(messages: list[dict] | None = None) -> dict:
    msgs = list(messages or [])
    return {
        "id": str(uuid4()),
        "title": _make_title_from_messages(msgs),
        "updated_at": _now_iso(),
        "messages": msgs,
        "pinned": False,
    }


def _sort_conversations(conversations: list[dict]) -> list[dict]:
    return sorted(
        conversations,
        key=lambda c: (
            0 if c.get("pinned") else 1,
            -(datetime.fromisoformat(str(c.get("updated_at", _now_iso()))).timestamp()),
        ),
    )


def _find_conversation(conversations: list[dict], conv_id: str) -> dict:
    for conv in conversations:
        if conv.get("id") == conv_id:
            return conv
    return conversations[0]


def _persist_conversations(conversations: list[dict], active_id: str) -> None:
    persisted = [_normalize_conversation(conv) for conv in conversations if isinstance(conv, dict) and _conversation_has_messages(conv)]
    if not persisted:
        if CONVERSATIONS_FILE.exists():
            CONVERSATIONS_FILE.unlink()
        return

    active = next((conv for conv in persisted if conv.get("id") == active_id), persisted[0])
    payload = {"active_id": str(active.get("id") or active_id), "conversations": persisted}
    CONVERSATIONS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    save_history(HISTORY_FILE, active.get("messages", []))


def _load_or_init_conversations() -> tuple[list[dict], str]:
    if CONVERSATIONS_FILE.exists():
        try:
            data = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
            conversations = data.get("conversations", [])
            if isinstance(conversations, list) and conversations:
                convs = [
                    _normalize_conversation(c)
                    for c in conversations
                    if isinstance(c, dict) and _conversation_has_messages(c)
                ]
                if convs:
                    active_id = str(data.get("active_id") or convs[0]["id"])
                    if not any(str(conv.get("id")) == active_id for conv in convs):
                        active_id = str(convs[0]["id"])
                    return convs, active_id
        except json.JSONDecodeError:
            pass

    old_messages = load_history(HISTORY_FILE)
    if old_messages:
        first = _new_conversation(old_messages)
        return [first], first["id"]

    fresh = _new_conversation([])
    return [fresh], fresh["id"]


def _render_history_sidebar(conversations: list[dict], active_id: str) -> str:
    items: list[str] = []
    for conv in _sort_conversations(conversations):
        conv_id = str(conv["id"])
        title = escape(str(conv.get("title") or "新对话"))
        updated = escape(str(conv.get("updated_at", "")).replace("T", " ")[:16])
        active_class = " active" if conv_id == active_id else ""
        pin_mark = "<span class='history-pin'>置顶</span>" if conv.get("pinned") else ""
        pin_text = "取消固定" if conv.get("pinned") else "固定"
        items.append(
            f"""
            <div class="history-item{active_class}" data-conv-id="{conv_id}">
              <button type="button" class="history-main" data-history-action="select" data-conv-id="{conv_id}">
                <div class="history-title-row">
                  <span class="history-title">{title}</span>
                  {pin_mark}
                </div>
                <div class="history-time">{updated}</div>
              </button>
              <div class="history-menu-wrap">
                <button type="button" class="history-menu-btn" data-history-menu-btn="1" data-conv-id="{conv_id}">•••</button>
                <div class="history-menu" id="history-menu-{conv_id}">
                  <button type="button" data-history-action="rename" data-conv-id="{conv_id}">重命名</button>
                  <button type="button" data-history-action="pin" data-conv-id="{conv_id}">{pin_text}</button>
                  <button type="button" class="danger" data-history-action="delete" data-conv-id="{conv_id}">删除</button>
                </div>
              </div>
            </div>
            """
        )
    return "<div class='history-list-wrap'>" + "".join(items) + "</div>"


def _format_assistant_content(thought: str, answer: str) -> str:
    _ = thought
    return (answer or "").strip()


def _render_trace_cards(trace_steps: list[dict]) -> str:
    if not trace_steps:
        return ""
    cards: list[str] = []
    for step in trace_steps:
        turn = int(step.get("turn", 0) or 0)
        thought = escape(str(step.get("thought", "") or "").strip())
        actions = step.get("actions", [])
        body: list[str] = []
        if thought:
            body.append(f"<div class='plan-line'><b>Thought</b> {thought}</div>")
        if isinstance(actions, list):
            for action in actions:
                tool_name = escape(str(action.get("tool", "") or ""))
                args_text = escape(str(action.get("arguments", "") or ""))
                obs_text = escape(str(action.get("observation", "") or ""))
                body.append(f"<div class='plan-line'><b>Action</b> {tool_name}({args_text})</div>")
                body.append(f"<div class='plan-line'><b>Observation</b> {obs_text[:360]}</div>")
        if not body:
            continue
        cards.append(
            "<details class='plan-card'>"
            f"<summary>第 {turn} 轮规划</summary>"
            + "".join(body)
            + "</details>"
        )
    return "<div class='plan-cards'>" + "".join(cards) + "</div>"


def _image_url(image_path: str) -> str:
    safe_path = urllib.parse.quote(image_path.replace("\\", "/"), safe="/:")
    return f"/gradio_api/file={safe_path}"


def _build_uploaded_image_html(image_path: str) -> str:
    url = _image_url(image_path)
    return (
        "<div class='uploaded-image-card'>"
        f"<a class='uploaded-image-open' href='{url}' target='_blank' rel='noopener noreferrer'>"
        f"<img class='uploaded-image-thumb' src='{url}' alt='uploaded image' />"
        "</a>"
        f"<a class='uploaded-image-download' href='{url}' download target='_blank' rel='noopener noreferrer'>↓</a>"
        "</div>"
    )


def _build_uploaded_files_html(file_names_or_paths: list[str]) -> str:
    if not file_names_or_paths:
        return ""
    cards: list[str] = []
    for item in file_names_or_paths:
        name = escape(Path(item).name)
        ext = escape((Path(item).suffix.lower().lstrip(".") or "FILE").upper())
        cards.append(
            "<div class='sent-file-chip'>"
            f"<span class='sent-file-name'>{name}</span>"
            f"<span class='sent-file-ext'>{ext}</span>"
            "</div>"
        )
    return "<div class='sent-files-wrap'>" + "".join(cards) + "</div>"


def _extract_edited_image_path(image_edit: dict | None) -> str | None:
    if isinstance(image_edit, str) and image_edit.strip():
        return image_edit
    if not isinstance(image_edit, dict):
        return None
    for key in ("composite", "background"):
        value = image_edit.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _normalize_file_paths(file_input: Any) -> list[str]:
    if not file_input:
        return []
    if isinstance(file_input, str):
        return [file_input]
    if isinstance(file_input, list):
        out: list[str] = []
        for item in file_input:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                out.append(item["path"])
        return out
    if isinstance(file_input, dict) and isinstance(file_input.get("path"), str):
        return [file_input["path"]]
    return []


def _stage_uploaded_files(file_paths: list[str]) -> list[str]:
    rel_paths: list[str] = []
    if not file_paths:
        return rel_paths
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for idx, p in enumerate(file_paths, start=1):
        src = Path(p)
        if not src.exists() or not src.is_file():
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", src.name)
        dst = UPLOADS_DIR / f"{ts}_{idx}_{safe_name}"
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        rel_paths.append(str(dst.relative_to(WORKSPACE_ROOT)).replace("\\", "/"))
    return rel_paths


def _on_file_selected(file_input: Any) -> tuple[list[str] | None, Any]:
    paths = _normalize_file_paths(file_input)
    if not paths:
        return None, gr.update(visible=False)

    valid: list[str] = []
    for p in paths:
        suffix = Path(p).suffix.lower()
        if suffix in READABLE_FILE_TYPES:
            valid.append(p)
    if not valid:
        return None, gr.update(visible=False)
    return valid, gr.update(visible=True)


def _render_attachment_strip(image_path: str | None, file_paths: list[str] | None) -> str:
    file_paths = file_paths or []
    has_any = bool(image_path) or bool(file_paths)
    if not has_any:
        return "<div class='attach-strip empty'></div>"

    cards: list[str] = []
    if image_path:
        url = _image_url(image_path)
        cards.append(
            "<div class='attach-card image'>"
            f"<img src='{url}' alt='image' />"
            "<button class='attach-remove' data-kind='image' data-index='0'>×</button>"
            "</div>"
        )

    for idx, fp in enumerate(file_paths):
        name = escape(Path(fp).name)
        ext = escape((Path(fp).suffix.lower().lstrip(".") or "file").upper())
        cards.append(
            "<div class='attach-card file'>"
            f"<div class='attach-title'>{name}</div>"
            f"<div class='attach-type'>{ext}</div>"
            f"<button class='attach-remove' data-kind='file' data-index='{idx}'>×</button>"
            "</div>"
        )

    return "<div class='attach-strip'>" + "".join(cards) + "</div>"


def _add_files_to_pending(file_input: Any, pending_image: str | None, pending_files: list[str] | None) -> tuple[list[str] | None, list[str], str]:
    paths = _normalize_file_paths(file_input)
    current = list(pending_files or [])
    if not paths:
        return None, current, _render_attachment_strip(pending_image, current)

    for p in paths:
        suffix = Path(p).suffix.lower()
        if suffix not in READABLE_FILE_TYPES:
            continue
        if p not in current:
            current.append(p)
    return None, current, _render_attachment_strip(pending_image, current)


def _remove_pending_attachment(action: str, pending_image: str | None, pending_files: list[str] | None) -> tuple[str | None, list[str], str]:
    image = pending_image
    files = list(pending_files or [])
    action = (action or "").strip()
    if action == "image":
        image = None
    elif action.startswith("file:"):
        try:
            idx = int(action.split(":", 1)[1])
            if 0 <= idx < len(files):
                files.pop(idx)
        except ValueError:
            pass
    return image, files, _render_attachment_strip(image, files)


def _read_uploaded_file_previews(file_rels: list[str], max_chars_each: int = 2500, max_files: int = 4) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not file_rels:
        return out
    tools = ToolRegistry(WORKSPACE_ROOT)
    for rel in file_rels[:max_files]:
        try:
            raw = tools.execute("read_text_file", json.dumps({"path": rel, "max_chars": max_chars_each}, ensure_ascii=False))
            data = json.loads(raw)
            content = str(data.get("content", "") or "").strip()
            fmt = str(data.get("detected_format", "") or "").strip()
            if content:
                out.append((rel, fmt, content))
        except Exception:
            continue
    return out


def _render_history_user_message(content: str) -> str:
    text_lines: list[str] = []
    image_paths: list[str] = []
    file_paths: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        image_match = re.match(r"^\[图片\]\s+(.+)$", line)
        if image_match:
            image_path = image_match.group(1).strip()
            if image_path:
                image_paths.append(image_path)
            continue
        file_match = re.match(r"^\[文件\]\s+(.+)$", line)
        if file_match:
            file_path = file_match.group(1).strip()
            if file_path:
                file_paths.append(file_path)
            continue
        text_lines.append(raw_line)

    pieces: list[str] = []
    text = "\n".join(text_lines).strip()
    if text:
        pieces.append(f"<div class='history-user-text'>{escape(text)}</div>")
    if image_paths:
        images_html = "".join(_build_uploaded_image_html(path) for path in image_paths)
        pieces.append(f"<div class='history-user-images'>{images_html}</div>")
    if file_paths:
        pieces.append(_build_uploaded_files_html(file_paths))
    return "".join(pieces) if pieces else escape(content.strip())


def _history_to_chat_messages(agent_history: list[dict]) -> list[dict[str, str]]:
    chat_messages: list[dict[str, str]] = []
    for item in agent_history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "assistant":
            chat_messages.append({"role": role, "content": _format_assistant_content("", content)})
        else:
            chat_messages.append({"role": role, "content": _render_history_user_message(content)})
    return chat_messages


def _render_chat_empty_state(visible: bool) -> str:
    cls = "chat-empty-state visible" if visible else "chat-empty-state"
    return (
        f"<div class='{cls}'>"
        "<div class='chat-empty-state-title'>pre OpenClaw</div>"
        "</div>"
    )


def _build_user_history_content(user_message: str, image_path: str | None, file_paths: list[str]) -> str:
    parts: list[str] = []
    text = (user_message or "").strip()
    if text:
        parts.append(text)
    if image_path:
        parts.append(f"[图片] {image_path}")
    for rel in file_paths:
        parts.append(f"[文件] {rel}")
    return "\n".join(parts).strip()


def _replace_last_user_message(messages: list[dict], content: str) -> list[dict]:
    updated = list(messages)
    for idx in range(len(updated) - 1, -1, -1):
        item = updated[idx]
        if isinstance(item, dict) and item.get("role") == "user":
            updated[idx] = {**item, "content": content}
            return updated
    if content:
        updated.append({"role": "user", "content": content})
    return updated


def _submit_message(
    user_message: str,
    pending_image: str | None,
    pending_files: list[str] | None,
    image_edit: dict | None,
    chat_messages: list[dict[str, str]] | None,
    conversations: list[dict] | None,
    current_conv_id: str,
) -> tuple[list[dict[str, str]], list[dict], str, str, Any, Any, str | None, list[str], str, str]:
    user_message = (user_message or "").strip()
    final_image_path = _extract_edited_image_path(image_edit) or pending_image
    selected_file_paths = list(pending_files or [])
    staged_file_rels = _stage_uploaded_files(selected_file_paths)
    convs = [_normalize_conversation(c) for c in list(conversations or [])]
    if not convs:
        convs, current_conv_id = _load_or_init_conversations()

    current_conv = _find_conversation(convs, current_conv_id)
    agent_history = list(current_conv.get("messages", []))

    if not user_message and not final_image_path and not staged_file_rels:
        return (
            chat_messages or _history_to_chat_messages(agent_history),
            convs,
            current_conv_id,
            "",
            None,
            None,
            None,
            [],
            _render_attachment_strip(None, []),
            _render_chat_empty_state(not bool(agent_history)),
            _render_history_sidebar(convs, current_conv_id),
        )

    ui_messages = list(chat_messages or [])
    try:
        thought_text = ""
        trace_steps: list[dict] = []
        previews = _read_uploaded_file_previews(staged_file_rels)
        if final_image_path:
            prompt = user_message or "请识别并分析这张图片。"
            if previews:
                prompt += "\n\n另外我还上传了文件，下面是提取到的内容预览："
                for rel, fmt, content in previews:
                    prompt += f"\n---\n文件: {rel}\n格式: {fmt or 'text'}\n内容:\n{content}"
            answer = run_vision_agent(prompt, final_image_path, mode="auto")
            user_content = _build_user_history_content(user_message, final_image_path, staged_file_rels)
            new_agent_history = list(agent_history) + [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": answer},
            ]
        else:
            effective_input = user_message
            if previews:
                joined_paths = "、".join(rel for rel, _, _ in previews)
                file_prompt = f"我上传了这些文件：{joined_paths}。请基于下面已提取内容回答。"
                for rel, fmt, content in previews:
                    file_prompt += f"\n---\n文件: {rel}\n格式: {fmt or 'text'}\n内容:\n{content}"
                effective_input = f"{user_message}\n\n{file_prompt}".strip()
            answer, new_agent_history, trace_steps = run_agent_with_trace(effective_input, agent_history)
            thoughts = [str(s.get("thought", "")).strip() for s in trace_steps if str(s.get("thought", "")).strip()]
            thought_text = "\n".join(thoughts)

        user_content = _build_user_history_content(user_message, final_image_path, selected_file_paths)
        new_agent_history = _replace_last_user_message(new_agent_history, user_content)

        current_conv["messages"] = new_agent_history
        if current_conv.get("title") in {"", "新对话"} or len(agent_history) == 0:
            current_conv["title"] = _make_title_from_messages(new_agent_history)
        current_conv["updated_at"] = _now_iso()
        _persist_conversations(convs, current_conv_id)

        user_display = _render_history_user_message(user_content)
        ui_messages.append({"role": "user", "content": user_display})
        plan_cards = _render_trace_cards(trace_steps)
        assistant_content = _format_assistant_content(thought_text, answer)
        if plan_cards:
            assistant_content = plan_cards + assistant_content
        ui_messages.append({"role": "assistant", "content": assistant_content})
        return ui_messages, convs, current_conv_id, "", None, None, None, [], _render_attachment_strip(None, []), _render_chat_empty_state(False), _render_history_sidebar(convs, current_conv_id)
    except Exception as exc:  # noqa: BLE001
        user_content = _build_user_history_content(user_message, final_image_path, selected_file_paths)
        user_display = _render_history_user_message(user_content)
        ui_messages.append({"role": "user", "content": user_display})
        ui_messages.append({"role": "assistant", "content": _format_assistant_content("", f"Agent Error: {exc}")})
        return ui_messages, convs, current_conv_id, "", None, None, None, [], _render_attachment_strip(None, []), _render_chat_empty_state(False), _render_history_sidebar(convs, current_conv_id)


def _submit_message_stream(
    user_message: str,
    pending_image: str | None,
    pending_files: list[str] | None,
    image_edit: dict | None,
    chat_messages: list[dict[str, str]] | None,
    conversations: list[dict] | None,
    current_conv_id: str,
):
    user_message = (user_message or "").strip()
    final_image_path = _extract_edited_image_path(image_edit) or pending_image
    selected_file_paths = list(pending_files or [])
    staged_file_rels = _stage_uploaded_files(selected_file_paths)
    convs = [_normalize_conversation(c) for c in list(conversations or [])]
    if not convs:
        convs, current_conv_id = _load_or_init_conversations()

    current_conv = _find_conversation(convs, current_conv_id)
    agent_history = list(current_conv.get("messages", []))
    if not user_message and not final_image_path and not selected_file_paths:
        yield (
            chat_messages or _history_to_chat_messages(agent_history),
            convs,
            current_conv_id,
            "",
            None,
            None,
            None,
            [],
            _render_attachment_strip(None, []),
            _render_chat_empty_state(not bool(agent_history)),
            _render_history_sidebar(convs, current_conv_id),
        )
        return

    thinking_messages = list(chat_messages or [])
    user_content = _build_user_history_content(user_message, final_image_path, selected_file_paths)
    user_display = _render_history_user_message(user_content)
    thinking_messages.append({"role": "user", "content": user_display})
    thinking_messages.append({"role": "assistant", "content": "<div class='ai-thinking'>思考中...</div>"})
    yield thinking_messages, convs, current_conv_id, user_message, None, None, final_image_path, selected_file_paths, _render_attachment_strip(final_image_path, selected_file_paths), _render_chat_empty_state(False), _render_history_sidebar(convs, current_conv_id)

    if final_image_path:
        # Vision path keeps existing non-stream flow.
        yield _submit_message(user_message, pending_image, pending_files, image_edit, chat_messages, convs, current_conv_id)
        return

    ui_messages = list(chat_messages or [])
    try:
        previews = _read_uploaded_file_previews(staged_file_rels)
        effective_input = user_message
        if previews:
            joined_paths = "、".join(rel for rel, _, _ in previews)
            file_prompt = f"我上传了这些文件：{joined_paths}。请基于下面已提取内容回答。"
            for rel, fmt, content in previews:
                file_prompt += f"\n---\n文件: {rel}\n格式: {fmt or 'text'}\n内容:\n{content}"
            effective_input = f"{user_message}\n\n{file_prompt}".strip()

        stream_text = ""
        final_answer = ""
        trace_steps: list[dict] = []
        new_agent_history = list(agent_history)
        stream_events = run_agent_stream_with_trace(effective_input, agent_history)
        for event in stream_events:
            if event.get("type") == "assistant_delta":
                stream_text += str(event.get("text", ""))
                partial_msgs = list(thinking_messages)
                partial_msgs[-1] = {"role": "assistant", "content": _format_assistant_content("", stream_text)}
                yield (
                    partial_msgs,
                    convs,
                    current_conv_id,
                    user_message,
                    None,
                    None,
                    final_image_path,
                    selected_file_paths,
                    _render_attachment_strip(final_image_path, selected_file_paths),
                    _render_chat_empty_state(False),
                    _render_history_sidebar(convs, current_conv_id),
                )
            elif event.get("type") == "final":
                final_answer = str(event.get("answer", "") or "")
                new_agent_history = list(event.get("history", []) or [])
                trace_steps = list(event.get("trace_steps", []) or [])

        new_agent_history = _replace_last_user_message(new_agent_history, user_content)

        current_conv["messages"] = new_agent_history
        if current_conv.get("title") in {"", "新对话"} or len(agent_history) == 0:
            current_conv["title"] = _make_title_from_messages(new_agent_history)
        current_conv["updated_at"] = _now_iso()
        _persist_conversations(convs, current_conv_id)

        user_display = _render_history_user_message(user_content)
        ui_messages.append({"role": "user", "content": user_display})
        assistant_content = _format_assistant_content("", final_answer or stream_text)
        plan_cards = _render_trace_cards(trace_steps)
        if plan_cards:
            assistant_content = plan_cards + assistant_content
        ui_messages.append({"role": "assistant", "content": assistant_content})
        yield (
            ui_messages,
            convs,
            current_conv_id,
            "",
            None,
            None,
            None,
            [],
            _render_attachment_strip(None, []),
            _render_chat_empty_state(False),
            _render_history_sidebar(convs, current_conv_id),
        )
    except Exception as exc:  # noqa: BLE001
        err_msgs = list(ui_messages)
        user_content = _build_user_history_content(user_message, final_image_path, selected_file_paths)
        user_display = _render_history_user_message(user_content)
        err_msgs.append({"role": "user", "content": user_display})
        err_msgs.append({"role": "assistant", "content": _format_assistant_content("", f"Agent Error: {exc}")})
        yield (
            err_msgs,
            convs,
            current_conv_id,
            "",
            None,
            None,
            None,
            [],
            _render_attachment_strip(None, []),
            _render_chat_empty_state(False),
            _render_history_sidebar(convs, current_conv_id),
        )


def _handle_history_action(
    action: str,
    target_id: str,
    payload: str,
    conversations: list[dict] | None,
    current_conv_id: str,
) -> tuple[str, list[dict], str, list[dict[str, str]], str, str]:
    convs = [_normalize_conversation(c) for c in list(conversations or [])]
    if not convs:
        convs, current_conv_id = _load_or_init_conversations()

    action = (action or "").strip()
    target_id = (target_id or "").strip()
    payload = (payload or "").strip()

    if action == "select" and target_id:
        selected = _find_conversation(convs, target_id)
        active_id = str(selected["id"])
        save_history(HISTORY_FILE, selected.get("messages", []))
        chat_messages = _history_to_chat_messages(selected.get("messages", []))
        return _render_history_sidebar(convs, active_id), convs, active_id, chat_messages, "", _render_attachment_strip(None, []), _render_chat_empty_state(not bool(chat_messages))

    if not target_id:
        active = _find_conversation(convs, current_conv_id)
        chat_messages = _history_to_chat_messages(active.get("messages", []))
        return _render_history_sidebar(convs, current_conv_id), convs, current_conv_id, chat_messages, "", _render_attachment_strip(None, []), _render_chat_empty_state(not bool(chat_messages))

    conv = _find_conversation(convs, target_id)
    if action == "rename":
        new_title = payload[:40].strip()
        if new_title:
            conv["title"] = new_title
            conv["updated_at"] = _now_iso()
            _persist_conversations(convs, current_conv_id)
    elif action == "pin":
        conv["pinned"] = not bool(conv.get("pinned"))
        _persist_conversations(convs, current_conv_id)
    elif action == "delete":
        convs = [c for c in convs if c.get("id") != target_id]
        if not convs:
            new_conv = _new_conversation([])
            convs = [new_conv]
            current_conv_id = new_conv["id"]
        elif current_conv_id == target_id:
            current_conv_id = _sort_conversations(convs)[0]["id"]
        _persist_conversations(convs, current_conv_id)

    active = _find_conversation(convs, current_conv_id)
    chat_messages = _history_to_chat_messages(active.get("messages", []))
    return _render_history_sidebar(convs, current_conv_id), convs, current_conv_id, chat_messages, "", _render_attachment_strip(None, []), _render_chat_empty_state(not bool(chat_messages))


def _new_chat(conversations: list[dict]) -> tuple[str, list[dict], str, list[dict[str, str]], str, str]:
    convs = [
        _normalize_conversation(c)
        for c in list(conversations or [])
        if isinstance(c, dict) and _conversation_has_messages(c)
    ]
    conv = _new_conversation([])
    convs.append(conv)
    active_id = conv["id"]
    return _render_history_sidebar(convs, active_id), convs, active_id, [], "", _render_attachment_strip(None, []), _render_chat_empty_state(True)


def _build_client_script() -> str:
    return """
    <script>
    (() => {
      const setTextboxValue = (selector, value) => {
        const el = document.querySelector(selector);
        if (!el) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set
          || Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      };

      const dispatchHistoryAction = (action, targetId, payload="") => {
        setTextboxValue("#history-action-box textarea, #history-action-box input", action);
        setTextboxValue("#history-target-box textarea, #history-target-box input", targetId);
        setTextboxValue("#history-payload-box textarea, #history-payload-box input", payload);
        const btn = document.querySelector("#history-dispatch button") || document.querySelector("#history-dispatch");
        if (btn) {
          window.setTimeout(() => btn.click(), 0);
        }
      };

      document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const historyButton = target.closest("[data-history-action]");
        if (historyButton instanceof HTMLElement) {
          event.preventDefault();
          event.stopPropagation();
          const action = historyButton.getAttribute("data-history-action") || "";
          const convId = historyButton.getAttribute("data-conv-id") || "";
          document.querySelectorAll(".history-menu.open").forEach((menu) => menu.classList.remove("open"));
          if (action === "select") {
            dispatchHistoryAction("select", convId, "");
            return;
          }
          if (action === "rename") {
            const currentTitle = document.querySelector(`.history-item[data-conv-id="${convId}"] .history-title`)?.innerText || "";
            const newTitle = window.prompt("输入新的会话名称", currentTitle);
            if (newTitle && newTitle.trim()) dispatchHistoryAction("rename", convId, newTitle.trim());
            return;
          }
          if (action === "pin") {
            dispatchHistoryAction("pin", convId, "");
            return;
          }
          if (action === "delete") {
            const ok = window.confirm("确定删除这条历史对话吗？");
            if (!ok) return;
            dispatchHistoryAction("delete", convId, "");
            return;
          }
        }
        if (target.closest("[data-history-menu-btn]")) {
          event.preventDefault();
          event.stopPropagation();
          const btn = target.closest("[data-history-menu-btn]");
          const convId = btn instanceof HTMLElement ? btn.getAttribute("data-conv-id") || "" : "";
          const menu = document.getElementById(`history-menu-${convId}`);
          if (!menu) return;
          const alreadyOpen = menu.classList.contains("open");
          document.querySelectorAll(".history-menu.open").forEach((node) => node.classList.remove("open"));
          if (!alreadyOpen) menu.classList.add("open");
          return;
        }
        if (!target.closest(".history-menu-wrap")) {
          document.querySelectorAll(".history-menu.open").forEach((menu) => menu.classList.remove("open"));
        }
      });

      document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.closest("#add-image-btn")) {
          event.preventDefault();
          event.stopPropagation();
          const menu = document.getElementById("add-menu");
          const anchor = document.querySelector("#add-image-btn button") || document.querySelector("#add-image-btn");
          if (menu) {
            if (anchor instanceof HTMLElement) {
              const r = anchor.getBoundingClientRect();
              const menuH = menu.offsetHeight || 70;
              menu.style.position = "fixed";
              menu.style.right = "auto";
              menu.style.bottom = "auto";
              menu.style.left = `${Math.max(8, r.left - 16)}px`;
              menu.style.top = `${Math.max(8, r.top - menuH - 8)}px`;
            }
            menu.classList.toggle("open");
          }
          return;
        }
        if (target.closest("#add-menu-image")) {
          event.preventDefault();
          event.stopPropagation();
          const fileInput = document.querySelector("#image-box input[type='file']");
          if (fileInput instanceof HTMLElement) fileInput.click();
          const menu = document.getElementById("add-menu");
          if (menu) menu.classList.remove("open");
          return;
        }
        if (target.closest("#add-menu-file")) {
          event.preventDefault();
          event.stopPropagation();
          const fileInput = document.querySelector("#file-box input[type='file']");
          if (fileInput instanceof HTMLInputElement) {
            fileInput.setAttribute("accept", ".txt,.md,.csv,.tsv,.json,.pdf,.docx,.xlsx,.pptx");
            fileInput.click();
          }
          const menu = document.getElementById("add-menu");
          if (menu) menu.classList.remove("open");
          return;
        }
        if (!target.closest("#add-menu") && !target.closest("#add-image-btn")) {
          const menu = document.getElementById("add-menu");
          if (menu) menu.classList.remove("open");
        }
        const removeBtn = target.closest(".attach-remove");
        if (removeBtn instanceof HTMLElement) {
          event.preventDefault();
          event.stopPropagation();
          const kind = removeBtn.getAttribute("data-kind") || "";
          const idx = removeBtn.getAttribute("data-index") || "0";
          const token = kind === "image" ? "image" : `file:${idx}`;
          setTextboxValue("#attach-remove-action textarea, #attach-remove-action input", token);
          const btn = document.querySelector("#attach-remove-dispatch button") || document.querySelector("#attach-remove-dispatch");
          if (btn instanceof HTMLElement) btn.click();
          return;
        }
        const previewToolBtn = target.closest("#image-preview .tools button, #image-preview [class*='tools'] button");
        const isPreviewExpandControl = !!target.closest(
          "#image-preview button[aria-label*='Expand'], " +
          "#image-preview button[aria-label*='放大'], " +
          "#image-preview [title*='Expand'], " +
          "#image-preview [title*='放大']"
        ) || (
          previewToolBtn instanceof HTMLButtonElement &&
          previewToolBtn.parentElement &&
          Array.from(previewToolBtn.parentElement.querySelectorAll("button")).indexOf(previewToolBtn) === 0
        );
        if (isPreviewExpandControl) {
          event.preventDefault();
          event.stopPropagation();
          const previewPathEl = document.querySelector("#preview-path-box textarea, #preview-path-box input");
          const rawPath = previewPathEl ? (previewPathEl.value || "").trim() : "";
          if (!rawPath) return;
          const normalized = rawPath.replace(/\\\\/g, "/");
          const encoded = encodeURI(normalized).replace(/#/g, "%23");
          const fileUrl = `/gradio_api/file=${encoded}`;
          window.open(fileUrl, "_blank", "noopener,noreferrer");
          return;
        }
      });

      const bindUi = () => {
        const chatRoot = document.querySelector("#chat-window");
        if (!chatRoot) {
          window.setTimeout(bindUi, 100);
          return;
        }

        if (!window.__enterBound) {
          window.__enterBound = true;
          document.addEventListener("keydown", (event) => {
            if (event.target && event.target.matches("#input-box textarea")) {
              if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                event.stopPropagation();
                const sendButton = document.querySelector("#send-btn button") || document.querySelector("#send-btn");
                if (sendButton) sendButton.click();
              }
            }
          }, true);
        }

        const nodes = [chatRoot, ...chatRoot.querySelectorAll("div")];
        const scrollBox = nodes.find((node) => {
          const style = window.getComputedStyle(node);
          return ["auto", "scroll"].includes(style.overflowY) && node.clientHeight > 0;
        }) || chatRoot;

        const applyChatLayout = () => {
          const content = Array.from(scrollBox.children).find((node) => node instanceof HTMLElement) || null;
          scrollBox.style.overscrollBehavior = "contain";
          scrollBox.style.paddingBottom = "0";
          if (content) {
            content.style.minHeight = "100%";
            content.style.display = "flex";
            content.style.flexDirection = "column";
            content.style.justifyContent = "flex-end";
          }
        };

        applyChatLayout();

        if (!chatRoot.dataset.scrollBound) {
          chatRoot.dataset.scrollBound = "1";
          const observer = new MutationObserver(() => {
            window.requestAnimationFrame(() => {
              applyChatLayout();
              scrollBox.scrollTop = Math.max(0, scrollBox.scrollHeight - scrollBox.clientHeight);
            });
          });
          observer.observe(chatRoot, { childList: true, subtree: true, characterData: true });
        }
      };

      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bindUi);
      else bindUi();
    })();
    </script>
    """


def build_demo() -> gr.Blocks:
    conversations, active_id = _load_or_init_conversations()
    active = _find_conversation(conversations, active_id)
    initial_chat_messages = _history_to_chat_messages(active.get("messages", []))
    initial_history_html = _render_history_sidebar(conversations, active_id)

    with gr.Blocks(title="Mini OpenClaw Chat", head=_build_client_script()) as demo:
        gr.HTML(
            """
            <div class="header-wrap">
              <div class="page-title">pre OpenClaw</div>
              <div class="page-meta">工作目录: """
            + escape(str(WORKSPACE_ROOT))
            + """</div>
            </div>
            """
        )

        with gr.Row(elem_id="main-row"):
            with gr.Column(scale=3, min_width=280, elem_id="left-panel"):
                gr.Markdown("### 历史对话")
                history_html = gr.HTML(initial_history_html, elem_id="history-list")
                new_chat_btn = gr.Button("+ 新建对话", elem_id="new-chat-btn")

            with gr.Column(scale=9, elem_id="right-panel"):
                with gr.Column(elem_id="chat-area"):
                    chat_empty_state = gr.HTML(_render_chat_empty_state(not bool(initial_chat_messages)), elem_id="chat-empty-state")
                    chatbot = gr.Chatbot(
                        value=initial_chat_messages,
                        buttons=["copy"],
                        layout="bubble",
                        height="100%",
                        sanitize_html=False,
                        render_markdown=True,
                        latex_delimiters=[
                            {"left": "$$", "right": "$$", "display": True},
                            {"left": "$", "right": "$", "display": False},
                            {"left": "\\(", "right": "\\)", "display": False},
                            {"left": "\\[", "right": "\\]", "display": True},
                        ],
                        elem_id="chat-window",
                    )

                image_box = gr.Image(type="filepath", label="图片", elem_id="image-box", elem_classes="image-picker")
                file_box = gr.File(
                    type="filepath",
                    label="文件",
                    visible=True,
                    elem_id="file-box",
                    file_types=list(READABLE_FILE_TYPES),
                    file_count="multiple",
                )
                attachments_html = gr.HTML(_render_attachment_strip(None, []), elem_id="attachments-html")
                attach_remove_action = gr.Textbox(value="", elem_id="attach-remove-action", elem_classes="bridge-hidden")
                attach_remove_dispatch = gr.Button("remove", elem_id="attach-remove-dispatch", elem_classes="bridge-hidden")
                image_editor = gr.ImageEditor(
                    label="图片批注（可框选重点）",
                    visible=False,
                    type="filepath",
                    brush=gr.Brush(colors=["#ff4d4f", "#00e5ff", "#ffd700"], default_size=6),
                    elem_id="image-editor",
                )

                with gr.Row(elem_id="input-wrap"):
                    add_image_btn = gr.Button("+", elem_id="add-image-btn", scale=0)
                    gr.HTML(
                        """
                        <div id="add-menu" class="add-menu">
                          <button id="add-menu-image" type="button">图片</button>
                          <button id="add-menu-file" type="button">文件</button>
                        </div>
                        """
                    )
                    message_box = gr.Textbox(
                        label="输入",
                        placeholder="给miniClaw发消息吧",
                        lines=4,
                        elem_id="input-box",
                        show_label=False,
                        interactive=True,
                        max_lines=12,
                        autofocus=True,
                    )
                    send_btn = gr.Button("↑", elem_id="send-btn", variant="primary", scale=0)

        conversations_state = gr.State(conversations)
        current_conv_id_state = gr.State(active_id)
        pending_image_state = gr.State(None)
        pending_files_state = gr.State([])

        history_action = gr.Textbox(value="", elem_id="history-action-box", elem_classes="bridge-hidden")
        history_target = gr.Textbox(value="", elem_id="history-target-box", elem_classes="bridge-hidden")
        history_payload = gr.Textbox(value="", elem_id="history-payload-box", elem_classes="bridge-hidden")
        history_dispatch = gr.Button("dispatch", elem_id="history-dispatch", elem_classes="bridge-hidden")
        send_btn.click(
            fn=_submit_message_stream,
            inputs=[message_box, pending_image_state, pending_files_state, image_editor, chatbot, conversations_state, current_conv_id_state],
            outputs=[chatbot, conversations_state, current_conv_id_state, message_box, image_box, file_box, pending_image_state, pending_files_state, attachments_html, chat_empty_state, history_html],
        )
        file_box.change(
            fn=_add_files_to_pending,
            inputs=[file_box, pending_image_state, pending_files_state],
            outputs=[file_box, pending_files_state, attachments_html],
            queue=False,
            show_progress="hidden",
        )
        image_box.change(
            fn=lambda path, files: (path, _render_attachment_strip(path, files or [])),
            inputs=[image_box, pending_files_state],
            outputs=[pending_image_state, attachments_html],
            queue=False,
            show_progress="hidden",
        )
        attach_remove_dispatch.click(
            fn=_remove_pending_attachment,
            inputs=[attach_remove_action, pending_image_state, pending_files_state],
            outputs=[pending_image_state, pending_files_state, attachments_html],
            queue=False,
            show_progress="hidden",
        )
        new_chat_btn.click(
            fn=_new_chat,
            inputs=[conversations_state],
            outputs=[history_html, conversations_state, current_conv_id_state, chatbot, message_box, attachments_html, chat_empty_state],
        )
        history_dispatch.click(
            fn=_handle_history_action,
            inputs=[history_action, history_target, history_payload, conversations_state, current_conv_id_state],
            outputs=[history_html, conversations_state, current_conv_id_state, chatbot, message_box, attachments_html, chat_empty_state],
        )

    return demo

def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port(preferred: int, max_tries: int = 30) -> int:
    for port in range(preferred, preferred + max_tries):
        if _is_port_available(port):
            return port
    raise RuntimeError(f"无法找到可用端口，尝试范围: {preferred}-{preferred + max_tries - 1}")


def main() -> None:
    demo = build_demo().queue()
    preferred_port = int(os.getenv("WEB_PORT", "7860"))
    server_port = _pick_port(preferred_port)
    if server_port != preferred_port:
        print(f"端口 {preferred_port} 已被占用，自动切换到 {server_port}")
    demo.launch(server_name="127.0.0.1", server_port=server_port, inbrowser=False, css="""
    html, body {
        height: 100%;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }
    .gradio-container {
        height: 100vh !important;
        max-width: 100% !important;
        padding: 0 !important;
        display: flex !important;
        flex-direction: column !important;
    }
    .gradio-container > .main,
    .gradio-container > .main > .wrap {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-height: 0;
    }
    .header-wrap {
        padding: 8px 16px;
        border-bottom: 1px solid #d1d5db;
    }
    .dark .header-wrap {
        border-bottom-color: #374151;
    }
    .page-title {
        font-size: 20px;
        font-weight: 700;
        line-height: 1.15;
    }
    .page-meta {
        color: #888;
        font-size: 12px;
    }
    #main-row {
        flex: 1 1 auto !important;
        height: calc(100vh - 96px) !important;
        max-height: calc(100vh - 96px) !important;
        min-height: 0 !important;
        flex-wrap: nowrap !important;
        align-items: stretch !important;
        padding: 6px 18px 10px 18px !important;
        gap: 18px !important;
        overflow: hidden !important;
    }
    #left-panel {
        height: 100% !important;
        max-height: 100% !important;
        min-height: 0 !important;
        border-right: 2px solid #d1d5db !important;
        padding-right: 18px !important;
        display: flex !important;
        flex-direction: column !important;
        position: relative !important;
        overflow: hidden !important;
    }
    .dark #left-panel {
        border-right-color: #4b5563 !important;
    }
    #right-panel {
        height: 100% !important;
        max-height: 100% !important;
        display: grid !important;
        grid-template-rows: minmax(0, 1fr) auto auto !important;
        row-gap: 0 !important;
        min-width: 0 !important;
        min-height: 0 !important;
        padding: 0 0 0 4px !important;
        overflow: hidden !important;
    }
    #chat-area {
        min-height: 0 !important;
        height: 100% !important;
        display: flex !important;
        flex-direction: column !important;
        overflow: hidden !important;
        position: relative !important;
    }
    #chat-empty-state {
        position: absolute !important;
        inset: 0 !important;
        display: none !important;
        align-items: center !important;
        justify-content: center !important;
        pointer-events: none !important;
        z-index: 3 !important;
        text-align: center !important;
    }
    #chat-empty-state.visible {
        display: flex !important;
    }
    .chat-empty-state-title {
        color: #9ca3af;
        font-size: 22px;
        font-weight: 600;
        letter-spacing: 0.03em;
        line-height: 1.2;
        text-shadow: 0 1px 0 rgba(0, 0, 0, 0.18);
    }
    #history-list {
        flex: 1 1 auto !important;
        min-height: 0 !important;
        max-height: calc(100vh - 230px) !important;
        overflow-y: auto !important;
        margin-bottom: 72px !important;
    }
    #new-chat-btn {
        position: absolute !important;
        left: 0 !important;
        right: 18px !important;
        bottom: 0 !important;
        z-index: 5 !important;
    }
    .history-list-wrap {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-right: 4px;
    }
    .history-item {
        position: relative;
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 8px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.02);
        transition: background 0.2s ease, border-color 0.2s ease;
    }
    .history-item.active {
        border-color: rgba(96, 165, 250, 0.55);
        background: rgba(96, 165, 250, 0.08);
    }
    .history-main {
        border: 0;
        background: transparent;
        text-align: left;
        padding: 12px 10px 12px 14px;
        color: inherit;
        cursor: pointer;
        width: 100%;
    }
    .history-title-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;
    }
    .history-title {
        font-size: 14px;
        font-weight: 600;
        line-height: 1.3;
        word-break: break-word;
    }
    .history-pin {
        font-size: 11px;
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.35);
        border-radius: 999px;
        padding: 1px 6px;
        flex-shrink: 0;
    }
    .history-time {
        font-size: 12px;
        color: #94a3b8;
    }
    .history-menu-wrap {
        position: relative;
        padding: 8px 8px 0 0;
    }
    .history-menu-btn {
        border: 0;
        background: transparent;
        color: #94a3b8;
        font-size: 16px;
        line-height: 1;
        padding: 8px;
        cursor: pointer;
        border-radius: 10px;
    }
    .history-menu-btn:hover {
        background: rgba(148, 163, 184, 0.1);
    }
    .history-menu {
        display: none;
        position: absolute;
        right: 0;
        top: 38px;
        min-width: 120px;
        padding: 6px;
        border-radius: 12px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        background: #15161a;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28);
        z-index: 40;
    }
    .history-menu.open {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .history-menu button {
        border: 0;
        background: transparent;
        color: #e5e7eb;
        text-align: left;
        padding: 8px 10px;
        border-radius: 8px;
        cursor: pointer;
    }
    .history-menu button:hover {
        background: rgba(148, 163, 184, 0.1);
    }
    .history-menu button.danger {
        color: #fca5a5;
    }
    #chat-window {
        flex: 1 1 0 !important;
        height: 100% !important;
        max-height: none !important;
        min-height: 0 !important;
        overflow-y: auto !important;
        border-radius: 8px !important;
        border: 1px solid #374151 !important;
        margin-top: 0 !important;
    }
    #attachments-html {
        margin: 0 !important;
        padding: 0 !important;
        border: 0 !important;
    }
    .attach-strip {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        overflow-y: hidden;
        padding: 0 2px 2px 2px;
        scrollbar-width: thin;
        border: 0 !important;
    }
    .attach-strip.empty {
        display: none !important;
    }
    .attach-card {
        position: relative;
        flex: 0 0 auto;
        width: 142px;
        height: 68px;
        border-radius: 12px;
        border: 1px solid rgba(148, 163, 184, 0.20);
        background: rgba(31, 35, 43, 0.92);
        overflow: hidden;
        padding: 10px 12px;
    }
    .attach-card.image {
        width: 110px;
        padding: 0;
    }
    .attach-card.image img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
    .attach-title {
        font-size: 13px;
        font-weight: 700;
        color: #e5e7eb;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin: 2px 0 6px 0;
    }
    .attach-type {
        font-size: 11px;
        font-weight: 600;
        color: #d1d5db;
        opacity: 0.9;
    }
    .attach-remove {
        position: absolute;
        right: 8px;
        top: 8px;
        width: 24px;
        height: 24px;
        border-radius: 999px;
        border: 1px solid rgba(255, 255, 255, 0.16);
        background: rgba(0, 0, 0, 0.72);
        color: #f3f4f6;
        font-size: 16px;
        line-height: 1;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    #image-box.image-picker {
        position: absolute !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    #preview-row {
        display: none !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        position: relative !important;
    }
    #preview-row:has(#image-preview:not([style*="display: none"])) {
        display: inline-flex !important;
        align-items: flex-start !important;
        justify-content: flex-start !important;
        width: fit-content !important;
        margin: 0 0 6px 0 !important;
    }
    #preview-card {
        position: relative !important;
        width: 72px !important;
        min-width: 72px !important;
        max-width: 72px !important;
        height: 72px !important;
        min-height: 72px !important;
        margin: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        background: transparent !important;
        overflow: visible !important;
        flex: 0 0 auto !important;
    }
    #image-preview {
        width: 72px !important;
        min-width: 72px !important;
        max-width: 72px !important;
        height: 72px !important;
        margin: 0 !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        border: 1px solid rgba(148, 163, 184, 0.25) !important;
        flex: 0 0 auto !important;
    }
    #image-preview img {
        object-fit: cover !important;
        width: 72px !important;
        height: 72px !important;
        max-width: 72px !important;
        max-height: 72px !important;
    }
    #preview-actions-row {
        display: none !important;
        position: absolute !important;
        top: -8px !important;
        right: -8px !important;
        gap: 0 !important;
        margin: 0 !important;
        min-height: 0 !important;
        z-index: 999 !important;
        pointer-events: auto !important;
    }
    #preview-row:has(#image-preview:not([style*="display: none"])) #preview-actions-row {
        display: flex !important;
    }
    #preview-delete-btn {
        flex: 0 0 auto !important;
        width: 24px !important;
        min-width: 24px !important;
        max-width: 24px !important;
        height: 24px !important;
        min-height: 24px !important;
        pointer-events: auto !important;
    }
    #preview-delete-btn button {
        width: 24px !important;
        min-width: 24px !important;
        max-width: 24px !important;
        height: 24px !important;
        min-height: 24px !important;
        padding: 0 !important;
        border-radius: 999px !important;
        border: 1px solid rgba(255, 255, 255, 0.16) !important;
        background: rgba(0, 0, 0, 0.86) !important;
        font-size: 15px !important;
        color: #fff !important;
        line-height: 1 !important;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35) !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        cursor: pointer !important;
        pointer-events: auto !important;
    }
    #preview-delete-btn,
    #preview-delete-btn button {
        opacity: 1 !important;
        visibility: visible !important;
    }
    /* Hide built-in expand/share; keep built-in download. */
    #image-preview .tools button:first-child,
    #image-preview [class*="tools"] button:first-child,
    #image-preview .tools button:last-child,
    #image-preview [class*="tools"] button:last-child,
    #image-preview button[aria-label*="Expand" i],
    #image-preview button[aria-label*="放大"],
    #image-preview [title*="Expand" i],
    #image-preview [title*="放大"],
    #image-preview button[aria-label*="Share" i],
    #image-preview button[aria-label*="分享"],
    #image-preview [title*="Share" i],
    #image-preview [title*="分享"] {
        display: none !important;
        pointer-events: none !important;
    }
    #file-box {
        position: absolute !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    #image-preview .tools button:nth-child(1),
    #image-preview [class*="tools"] button:nth-child(1) {
        display: none !important;
        pointer-events: none !important;
    }
    #image-editor {
        margin: 0 0 8px 0 !important;
    }
    #file-hint {
        display: none !important;
    }
    #clear-file-btn,
    #clear-file-btn button {
        position: absolute !important;
        right: 98px !important;
        bottom: 10px !important;
        z-index: 11 !important;
        min-width: 30px !important;
        width: 30px !important;
        height: 30px !important;
        padding: 0 !important;
        border-radius: 999px !important;
        border: 1px solid rgba(148, 163, 184, 0.35) !important;
        background: rgba(0, 0, 0, 0.55) !important;
        color: #e5e7eb !important;
        font-size: 16px !important;
        line-height: 1 !important;
    }
    #add-image-btn,
    #add-image-btn button {
        position: absolute !important;
        right: 56px !important;
        bottom: 10px !important;
        z-index: 11 !important;
        min-width: 34px !important;
        width: 34px !important;
        height: 34px !important;
        padding: 0 !important;
        border-radius: 999px !important;
        font-size: 18px !important;
        line-height: 1 !important;
    }
    #add-menu {
        position: fixed !important;
        right: auto !important;
        bottom: auto !important;
        z-index: 12 !important;
        display: none !important;
        flex-direction: column !important;
        gap: 4px !important;
        padding: 6px !important;
        border-radius: 10px !important;
        background: rgba(20, 21, 25, 0.94) !important;
        border: 1px solid rgba(148, 163, 184, 0.25) !important;
        box-shadow: 0 8px 22px rgba(0, 0, 0, 0.35) !important;
    }
    #add-menu.open {
        display: flex !important;
    }
    #add-menu button {
        min-width: 64px !important;
        height: 28px !important;
        padding: 0 10px !important;
        border-radius: 8px !important;
        border: 1px solid rgba(148, 163, 184, 0.28) !important;
        background: rgba(39, 41, 50, 0.95) !important;
        color: #e5e7eb !important;
        font-size: 12px !important;
        line-height: 1 !important;
        margin: 0 !important;
        cursor: pointer !important;
    }
    #add-menu button:hover {
        background: rgba(59, 130, 246, 0.22) !important;
    }
    #input-wrap {
        margin-top: 0 !important;
        padding-top: 0 !important;
        border-top: 0 !important;
        flex: 0 0 auto !important;
        position: relative !important;
        display: block !important;
    }
    #input-wrap::before,
    #input-wrap::after {
        display: none !important;
    }
    .sent-files-wrap {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 4px;
    }
    .sent-file-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border-radius: 10px;
        border: 1px solid rgba(148, 163, 184, 0.35);
        background: rgba(31, 35, 43, 0.75);
        max-width: 280px;
    }
    .sent-file-name {
        font-size: 12px;
        color: #e5e7eb;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 220px;
    }
    .sent-file-ext {
        font-size: 10px;
        color: #cbd5e1;
        font-weight: 700;
    }
    #input-box {
        width: 100% !important;
    }
    #input-box textarea {
        min-height: 96px !important;
        padding-left: 14px !important;
        padding-right: 98px !important;
        padding-bottom: 12px !important;
    }
    #send-btn,
    #send-btn button {
        position: absolute !important;
        right: 10px !important;
        bottom: 10px !important;
        z-index: 10 !important;
        min-width: 34px !important;
        width: 34px !important;
        min-height: 34px !important;
        height: 34px !important;
        padding: 0 !important;
        border-radius: 999px !important;
        white-space: nowrap !important;
        font-size: 18px !important;
        line-height: 1 !important;
    }
    .bridge-hidden {
        display: none !important;
    }
    footer, .footer, .gradio-container .built-with {
        display: none !important;
    }
    .ai-thought {
        color: #9ca3af;
        font-size: 13px;
        margin-bottom: 10px;
        white-space: normal;
        border-left: 2px solid #4b5563;
        padding-left: 10px;
    }
    .ai-thinking {
        color: #9ca3af;
        font-size: 14px;
        letter-spacing: 0.02em;
    }
    .plan-cards {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin: 0 0 10px 0;
    }
    .plan-card {
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 10px;
        background: rgba(31, 35, 43, 0.45);
        padding: 6px 8px;
    }
    .plan-card summary {
        cursor: pointer;
        font-size: 12px;
        color: #9ca3af;
        font-weight: 600;
        outline: none;
    }
    .plan-line {
        font-size: 12px;
        color: #d1d5db;
        line-height: 1.45;
        margin-top: 4px;
        word-break: break-word;
    }
    .vision-card {
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 12px;
        background: rgba(31, 35, 43, 0.45);
        padding: 8px 10px;
        margin-bottom: 12px;
    }
    .vision-card summary {
        cursor: pointer;
        font-size: 13px;
        font-weight: 700;
        color: #dbeafe;
        outline: none;
    }
    .vision-card-body {
        margin-top: 8px;
        font-size: 13px;
        line-height: 1.6;
        color: #e5e7eb;
        word-break: break-word;
    }
    .uploaded-image-card {
        position: relative;
        display: inline-block;
        margin-top: 10px;
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(148, 163, 184, 0.18);
        background: rgba(255, 255, 255, 0.03);
        max-width: min(320px, 60vw);
    }
    .uploaded-image-open {
        display: block;
    }
    .uploaded-image-thumb {
        display: block;
        width: min(320px, 60vw);
        max-width: 320px;
        max-height: 280px;
        object-fit: cover;
    }
    .uploaded-image-download {
        position: absolute;
        right: 8px;
        top: 8px;
        width: 28px;
        height: 28px;
        border-radius: 999px;
        background: rgba(17, 24, 39, 0.82);
        color: #fff !important;
        text-decoration: none !important;
        font-weight: 700;
        line-height: 28px;
        text-align: center;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.28);
    }
    """)


if __name__ == "__main__":
    main()

