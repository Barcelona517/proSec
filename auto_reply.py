from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import json

from openai import OpenAI

from config import AUTO_REPLY_MODEL, AUTO_REPLY_STATE_FILE, PERSONA_FILE
from llm_client import build_client
from qq_tools import QQAutomation, QQAutomationError


def load_persona(path: Path = PERSONA_FILE) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_auto_reply_state(path: Path = AUTO_REPLY_STATE_FILE) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def save_auto_reply_state(state: dict, path: Path = AUTO_REPLY_STATE_FILE) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint_messages(messages: list[str]) -> str:
    joined = "\n".join(messages).strip()
    return sha1(joined.encode("utf-8")).hexdigest()


def read_qq_chat_messages(chat_name: str, limit: int = 20) -> list[str]:
    qq = QQAutomation()
    qq.open_chat(chat_name)
    return qq.read_messages(limit=limit)


def generate_reply_for_chat(
    chat_name: str,
    messages: list[str],
    client: OpenAI | None = None,
    persona_text: str | None = None,
) -> str:
    client = client or build_client()
    persona_text = persona_text if persona_text is not None else load_persona()

    transcript = "\n".join(f"- {line}" for line in messages[-20:]).strip()
    prompt = (
        "你现在要代替用户回复一个 QQ 会话。\n"
        f"会话名称：{chat_name}\n\n"
        "以下是用户的人设，请严格参考，但不要机械复述：\n"
        f"{persona_text or '（当前未填写人设）'}\n\n"
        "以下是最近聊天内容：\n"
        f"{transcript or '（没有读取到聊天内容）'}\n\n"
        "请生成一条适合直接发送的中文回复。\n"
        "要求：\n"
        "1. 简短自然，像真人聊天。\n"
        "2. 不要解释思路。\n"
        "3. 不要使用引号包裹回复。\n"
        "4. 不要暴露自己是 AI，除非人设明确要求。\n"
    )

    resp = client.chat.completions.create(
        model=AUTO_REPLY_MODEL,
        messages=[
            {"role": "system", "content": "你是一个擅长模仿聊天风格的中文回复助手。只输出最终要发送的消息文本。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )
    return (resp.choices[0].message.content or "").strip()


def bootstrap_auto_reply_state(chat_name: str, limit: int = 20) -> dict:
    messages = read_qq_chat_messages(chat_name, limit=limit)
    state = load_auto_reply_state()
    state[chat_name] = {
        "last_seen_fingerprint": fingerprint_messages(messages),
        "last_reply": "",
    }
    save_auto_reply_state(state)
    return {
        "ok": True,
        "chat": chat_name,
        "status": "bootstrapped",
        "messages_seen": len(messages),
    }


def auto_reply_once(chat_name: str, limit: int = 20, dry_run: bool = False) -> dict:
    qq = QQAutomation()
    persona_text = load_persona()
    before_messages = read_qq_chat_messages(chat_name, limit=limit)
    before_fingerprint = fingerprint_messages(before_messages)

    state = load_auto_reply_state()
    chat_state = state.get(chat_name, {})
    if chat_state.get("last_seen_fingerprint") == before_fingerprint:
        return {
            "ok": True,
            "chat": chat_name,
            "status": "no_new_message",
            "reply": "",
        }

    reply = generate_reply_for_chat(chat_name, before_messages, persona_text=persona_text)
    if not reply:
        return {
            "ok": False,
            "chat": chat_name,
            "status": "empty_reply",
            "reply": "",
        }

    preview = qq.preview_send_targets(chat_name)
    if not preview.get("can_send_safely"):
        raise QQAutomationError(f"自动回复前无法安全确认 QQ 会话 `{chat_name}`。")

    if not dry_run:
        qq.send_message(chat_name, reply, confirmed_name=str(preview.get("selected_name", "")))
        after_messages = read_qq_chat_messages(chat_name, limit=limit)
        after_fingerprint = fingerprint_messages(after_messages)
    else:
        after_fingerprint = before_fingerprint

    state[chat_name] = {
        "last_seen_fingerprint": after_fingerprint,
        "last_reply": reply,
    }
    save_auto_reply_state(state)

    return {
        "ok": True,
        "chat": chat_name,
        "status": "replied" if not dry_run else "drafted",
        "reply": reply,
    }
