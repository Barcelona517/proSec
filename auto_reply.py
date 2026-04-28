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
    attach = qq.attach_or_launch()
    if chat_name not in str(attach.get("window_title", "")):
        qq.open_chat(chat_name)
    return qq.read_messages(limit=limit)


def read_qq_chat_message_entries(chat_name: str, limit: int = 20) -> list[dict[str, str]]:
    qq = QQAutomation()
    attach = qq.attach_or_launch()
    if chat_name not in str(attach.get("window_title", "")):
        qq.open_chat(chat_name)
    return qq.read_message_entries(limit=limit)


def collapse_message_turns(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for entry in entries:
        side = entry.get("side", "")
        text = str(entry.get("text", "")).strip()
        if not side or not text:
            continue
        if turns and turns[-1]["side"] == side:
            turns[-1]["text"] = f"{turns[-1]['text']}\n{text}"
        else:
            turns.append({"side": side, "text": text})
    return turns


def latest_incoming_turn(entries: list[dict[str, str]]) -> dict[str, str] | None:
    turns = collapse_message_turns(entries)
    incoming_turns = [turn for turn in turns if turn.get("side") == "incoming" and turn.get("text")]
    if not incoming_turns:
        return None
    return incoming_turns[-1]


def latest_incoming_fingerprint(entries: list[dict[str, str]]) -> str:
    latest_turn = latest_incoming_turn(entries)
    if not latest_turn:
        return ""
    return fingerprint_messages([latest_turn["text"]])


def generate_reply_for_chat(
    chat_name: str,
    entries: list[dict[str, str]],
    client: OpenAI | None = None,
    persona_text: str | None = None,
) -> str:
    client = client or build_client()
    persona_text = persona_text if persona_text is not None else load_persona()
    turns = collapse_message_turns(entries)
    recent_context = []
    for turn in turns[-8:]:
        role = "对方" if turn.get("side") == "incoming" else "我方"
        recent_context.append(f"- {role}: {turn['text']}")
    transcript = "\n".join(recent_context).strip()
    latest_turn = latest_incoming_turn(entries)
    latest_incoming = latest_turn["text"] if latest_turn else ""
    prompt = (
        "你现在要代替用户回复一个 QQ 会话。\n"
        f"会话名称：{chat_name}\n\n"
        "以下是用户的人设，请严格参考，但不要机械复述：\n"
        f"{persona_text or '（当前未填写人设）'}\n\n"
        "只回复对方最近一轮发言，不要回复我方自己刚发出去的内容。\n"
        "如果对方连续发了多句，把它们视为同一轮发言，只回一条。\n"
        f"对方最近一轮发言：{latest_incoming or '（没有读取到对方新消息）'}\n\n"
        "以下是最近聊天内容：\n"
        f"{transcript or '（没有读取到聊天内容）'}\n\n"
        "请生成一条适合直接发送的中文回复。\n"
        "要求：\n"
        "1. 只回复一条，简短自然，像真人聊天。\n"
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
    entries = read_qq_chat_message_entries(chat_name, limit=limit)
    state = load_auto_reply_state()
    state[chat_name] = {
        "last_seen_fingerprint": latest_incoming_fingerprint(entries),
        "last_reply": "",
    }
    save_auto_reply_state(state)
    return {
        "ok": True,
        "chat": chat_name,
        "status": "bootstrapped",
        "messages_seen": len(entries),
    }


def auto_reply_once(chat_name: str, limit: int = 20, dry_run: bool = False) -> dict:
    qq = QQAutomation()
    persona_text = load_persona()
    before_entries = read_qq_chat_message_entries(chat_name, limit=limit)
    before_fingerprint = latest_incoming_fingerprint(before_entries)

    state = load_auto_reply_state()
    chat_state = state.get(chat_name, {})
    if chat_state.get("last_seen_fingerprint") == before_fingerprint:
        return {
            "ok": True,
            "chat": chat_name,
            "status": "no_new_message",
            "reply": "",
        }

    if not before_fingerprint:
        return {
            "ok": True,
            "chat": chat_name,
            "status": "no_incoming_message",
            "reply": "",
        }

    reply = generate_reply_for_chat(chat_name, before_entries, persona_text=persona_text)
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
        after_entries = read_qq_chat_message_entries(chat_name, limit=limit)
        after_fingerprint = latest_incoming_fingerprint(after_entries)
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
