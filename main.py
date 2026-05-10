from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any, Iterator

from config import HISTORY_FILE, MAX_TURNS, MODEL_NAME, SYSTEM_PROMPT, WORKSPACE_ROOT
from llm_client import build_client
from tooling import ToolExecutionError, ToolRegistry


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


def save_history(path: Path, messages: list[dict]) -> None:
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def _looks_like_brief_topic_query(user_input: str) -> bool:
    text = user_input.strip()
    if not text or "\n" in text or len(text) > 24:
        return False

    lowered = text.lower()
    action_words = [
        "请",
        "帮我",
        "给我",
        "解释",
        "介绍",
        "搜索",
        "查",
        "看看",
        "打开",
        "读取",
        "写入",
        "删除",
        "存在",
        "还在",
        "目录",
        "文件",
        "please",
        "search",
        "find",
        "open",
        "read",
        "write",
        "delete",
        "exists",
        "file",
    ]
    if any(word in lowered for word in action_words):
        return False

    if any(ch in text for ch in "，。！？；,.!?;:/\\()[]{}<>\"'`"):
        return False

    tokens = re.split(r"\s+", text)
    return len(tokens) <= 4


def _looks_like_fresh_file_check(user_input: str) -> bool:
    text = user_input.strip().lower()
    hints = [
        "文件",
        "目录",
        "文件夹",
        "还在",
        "存在",
        "删",
        "删除",
        "现在没",
        "当前没",
        "实时",
        "file",
        "folder",
        "directory",
        "exists",
        "exist",
        "deleted",
        "remove",
        "removed",
        "current",
    ]
    return any(hint in text for hint in hints)


def _build_messages(user_input: str, history: list[dict]) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    if _looks_like_brief_topic_query(user_input):
        messages.append(
            {
                "role": "system",
                "content": (
                    "用户这次只输入了一个简短名词或短语。"
                    "默认将其理解为：用户想了解这个对象的相关信息、背景、用法、特点或来源。"
                    "如果需要外部知识，优先调用 search_web；回答时直接给出简介和关键信息。"
                ),
            }
        )

    if _looks_like_fresh_file_check(user_input):
        messages.append(
            {
                "role": "system",
                "content": (
                    "这次问题涉及文件或目录的当前状态。"
                    "你必须重新调用本地文件工具做实时检查，不能直接引用旧对话里之前看到的文件列表或旧结论。"
                ),
            }
        )

    messages.append({"role": "user", "content": user_input})
    return messages


def _run_agent_core(user_input: str, history: list[dict]) -> tuple[str, list[dict], list[dict[str, Any]]]:
    client = build_client()
    tools = ToolRegistry(WORKSPACE_ROOT)
    messages = _build_messages(user_input, history)

    final_answer = "未获得最终回答。"
    last_tool_error = ""
    trace_steps: list[dict[str, Any]] = []

    for turn in range(1, MAX_TURNS + 1):
        print(f"\n=== Turn {turn} ===")
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools.all_for_openai(),
            tool_choice="auto",
            temperature=0.2,
        )

        msg = resp.choices[0].message
        assistant_message = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_message["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
        messages.append(assistant_message)

        thought = (msg.content or "").strip()
        if thought:
            print(f"Thought/Reply: {thought}")

        step: dict[str, Any] = {"turn": turn, "thought": thought, "actions": []}

        if not msg.tool_calls:
            final_answer = msg.content or "(空回答)"
            trace_steps.append(step)
            break

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            raw_args = tc.function.arguments
            print(f"Action: {tool_name}({raw_args})")

            try:
                tool_result = tools.execute(tool_name, raw_args)
                parsed = json.loads(tool_result)
                if isinstance(parsed, dict) and parsed.get("ok") is False:
                    last_tool_error = str(parsed.get("error", "")).strip()
            except ToolExecutionError as exc:
                tool_result = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                last_tool_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                tool_result = json.dumps({"ok": False, "error": f"工具执行异常: {exc}"}, ensure_ascii=False)
                last_tool_error = f"工具执行异常: {exc}"

            print(f"Observation: {tool_result}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
            step["actions"].append(
                {
                    "tool": tool_name,
                    "arguments": raw_args,
                    "observation": tool_result,
                }
            )

        trace_steps.append(step)

    if final_answer == "未获得最终回答。":
        if last_tool_error:
            final_answer = f"这次没有成功拿到结果，最后一次工具报错是：{last_tool_error}"
        else:
            final_answer = f"这次没有成功拿到最终回答，可能是达到最大轮数 {MAX_TURNS} 仍未结束。"

    new_history = [m for m in messages if m["role"] != "system"]
    return final_answer, new_history, trace_steps


def run_agent(user_input: str, history: list[dict]) -> tuple[str, list[dict]]:
    answer, new_history, _trace = _run_agent_core(user_input, history)
    return answer, new_history


def run_agent_with_trace(user_input: str, history: list[dict]) -> tuple[str, list[dict], list[dict[str, Any]]]:
    return _run_agent_core(user_input, history)


def run_agent_stream_with_trace(user_input: str, history: list[dict]) -> Iterator[dict[str, Any]]:
    client = build_client()
    tools = ToolRegistry(WORKSPACE_ROOT)
    messages = _build_messages(user_input, history)

    final_answer = "未获得最终回答。"
    last_tool_error = ""
    trace_steps: list[dict[str, Any]] = []

    for turn in range(1, MAX_TURNS + 1):
        print(f"\n=== Turn {turn} ===")
        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools.all_for_openai(),
            tool_choice="auto",
            temperature=0.2,
            stream=True,
        )

        content_parts: list[str] = []
        tool_call_buf: dict[int, dict[str, str]] = {}

        for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "assistant_delta", "text": delta.content}
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = int(tc.index or 0)
                    slot = tool_call_buf.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

        thought = "".join(content_parts).strip()
        if thought:
            print(f"Thought/Reply: {thought}")

        tool_calls = [
            {
                "id": v["id"],
                "type": "function",
                "index": idx,
                "function": {"name": v["name"], "arguments": v["arguments"]},
            }
            for idx, v in sorted(tool_call_buf.items(), key=lambda kv: kv[0])
            if v["name"]
        ]

        assistant_message: dict[str, Any] = {"role": "assistant", "content": thought}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        step: dict[str, Any] = {"turn": turn, "thought": thought, "actions": []}

        if not tool_calls:
            final_answer = thought or "(空回答)"
            trace_steps.append(step)
            break

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"]
            print(f"Action: {tool_name}({raw_args})")
            try:
                tool_result = tools.execute(tool_name, raw_args)
                parsed = json.loads(tool_result)
                if isinstance(parsed, dict) and parsed.get("ok") is False:
                    last_tool_error = str(parsed.get("error", "")).strip()
            except ToolExecutionError as exc:
                tool_result = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                last_tool_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                tool_result = json.dumps({"ok": False, "error": f"工具执行异常: {exc}"}, ensure_ascii=False)
                last_tool_error = f"工具执行异常: {exc}"

            print(f"Observation: {tool_result}")
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
            step["actions"].append(
                {
                    "tool": tool_name,
                    "arguments": raw_args,
                    "observation": tool_result,
                }
            )

        trace_steps.append(step)

    if final_answer == "未获得最终回答。":
        if last_tool_error:
            final_answer = f"这次没有成功拿到结果，最后一次工具报错是：{last_tool_error}"
        else:
            final_answer = f"这次没有成功拿到最终回答，可能是达到最大轮数 {MAX_TURNS} 仍未结束。"

    new_history = [m for m in messages if m["role"] != "system"]
    yield {
        "type": "final",
        "answer": final_answer,
        "history": new_history,
        "trace_steps": trace_steps,
    }


def main() -> None:
    print("Mini OpenClaw 已启动。输入 exit 退出。")
    print(f"受限工作目录: {WORKSPACE_ROOT}")
    history = load_history(HISTORY_FILE)

    while True:
        user_input = input("\nYou> ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break

        try:
            answer, history = run_agent(user_input, history)
        except Exception as exc:  # noqa: BLE001
            print(f"Agent Error: {exc}")
            continue

        save_history(HISTORY_FILE, history)
        print(f"\nFinal Answer: {answer}")


if __name__ == "__main__":
    main()
