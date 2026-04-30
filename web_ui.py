from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
from html import escape
import io
import json
import os
import re
import socket
import urllib.parse
from uuid import uuid4

import gradio as gr

from config import HISTORY_FILE, MODEL_NAME, VISION_MODEL, WORKSPACE_ROOT
from main import load_history, run_agent, save_history
from vision_agent import run_vision_agent


os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

CONVERSATIONS_FILE = HISTORY_FILE.with_name("conversations.json")


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
    payload = {"active_id": active_id, "conversations": conversations}
    CONVERSATIONS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    active = _find_conversation(conversations, active_id)
    save_history(HISTORY_FILE, active.get("messages", []))


def _load_or_init_conversations() -> tuple[list[dict], str]:
    if CONVERSATIONS_FILE.exists():
        try:
            data = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
            conversations = data.get("conversations", [])
            active_id = str(data.get("active_id", ""))
            if isinstance(conversations, list) and conversations:
                convs = [_normalize_conversation(c) for c in conversations if isinstance(c, dict)]
                if convs:
                    if not any(c.get("id") == active_id for c in convs):
                        active_id = convs[0]["id"]
                    return convs, active_id
        except json.JSONDecodeError:
            pass

    old_messages = load_history(HISTORY_FILE)
    first = _new_conversation(old_messages)
    conversations = [first]
    _persist_conversations(conversations, first["id"])
    return conversations, first["id"]


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
              <button class="history-main" onclick="window.__historyAction('select', '{conv_id}')">
                <div class="history-title-row">
                  <span class="history-title">{title}</span>
                  {pin_mark}
                </div>
                <div class="history-time">{updated}</div>
              </button>
              <div class="history-menu-wrap">
                <button class="history-menu-btn" onclick="window.__toggleHistoryMenu(event, '{conv_id}')">•••</button>
                <div class="history-menu" id="history-menu-{conv_id}">
                  <button onclick="window.__historyRename('{conv_id}')">重命名</button>
                  <button onclick="window.__historyAction('pin', '{conv_id}')">{pin_text}</button>
                  <button class="danger" onclick="window.__historyAction('delete', '{conv_id}')">删除</button>
                </div>
              </div>
            </div>
            """
        )
    return "<div class='history-list-wrap'>" + "".join(items) + "</div>"


def _format_assistant_content(thought: str, answer: str) -> str:
    answer = (answer or "").strip()
    thought = (thought or "").strip()
    if thought and thought != answer:
        return f"> 思考\n> {thought.replace(chr(10), chr(10) + '> ')}\n\n{answer}"
    return answer


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
            cleaned_user = re.sub(
                r"(?im)^\[图片\]\s+.+(?:\\|/)(?:temp|tmp)(?:\\|/).*?\.(?:png|jpg|jpeg|webp|bmp)\s*$",
                "[图片已上传]",
                content.strip(),
            )
            chat_messages.append({"role": role, "content": cleaned_user})
    return chat_messages


def _submit_message(
    user_message: str,
    image_path: str | None,
    image_edit: dict | None,
    chat_messages: list[dict[str, str]] | None,
    conversations: list[dict] | None,
    current_conv_id: str,
) -> tuple[list[dict[str, str]], list[dict], str, str, str | None, dict | None, str | None, str]:
    user_message = (user_message or "").strip()
    final_image_path = _extract_edited_image_path(image_edit) or image_path
    convs = [_normalize_conversation(c) for c in list(conversations or [])]
    if not convs:
        convs, current_conv_id = _load_or_init_conversations()

    current_conv = _find_conversation(convs, current_conv_id)
    agent_history = list(current_conv.get("messages", []))

    if not user_message and not final_image_path:
        return (
            chat_messages or _history_to_chat_messages(agent_history),
            convs,
            current_conv_id,
            "",
            None,
            None,
            None,
            _render_history_sidebar(convs, current_conv_id),
        )

    ui_messages = list(chat_messages or [])
    try:
        thought_text = ""
        if final_image_path:
            prompt = user_message or "请识别并分析这张图片。"
            answer = run_vision_agent(prompt, final_image_path)
            new_agent_history = list(agent_history) + [
                {"role": "user", "content": f"{prompt}\n[图片] {final_image_path}"},
                {"role": "assistant", "content": answer},
            ]
        else:
            buf = io.StringIO()
            with redirect_stdout(buf):
                answer, new_agent_history = run_agent(user_message, agent_history)
            logs = buf.getvalue().splitlines()
            thoughts = [line.split("Thought/Reply:", 1)[1].strip() for line in logs if "Thought/Reply:" in line]
            thought_text = "\n".join([t for t in thoughts if t])

        current_conv["messages"] = new_agent_history
        if current_conv.get("title") in {"", "新对话"} or len(agent_history) == 0:
            current_conv["title"] = _make_title_from_messages(new_agent_history)
        current_conv["updated_at"] = _now_iso()
        _persist_conversations(convs, current_conv_id)

        user_display = user_message or "请识别并分析这张图片。"
        if final_image_path:
            user_display = f"{user_display}\n\n{_build_uploaded_image_html(final_image_path)}"
        ui_messages.append({"role": "user", "content": user_display})
        ui_messages.append({"role": "assistant", "content": _format_assistant_content(thought_text, answer)})
        return ui_messages, convs, current_conv_id, "", None, None, None, _render_history_sidebar(convs, current_conv_id)
    except Exception as exc:  # noqa: BLE001
        user_display = user_message or "请识别并分析这张图片。"
        if final_image_path:
            user_display = f"{user_display}\n\n{_build_uploaded_image_html(final_image_path)}"
        ui_messages.append({"role": "user", "content": user_display})
        ui_messages.append({"role": "assistant", "content": _format_assistant_content("", f"Agent Error: {exc}")})
        return ui_messages, convs, current_conv_id, "", None, None, None, _render_history_sidebar(convs, current_conv_id)


def _submit_message_stream(
    user_message: str,
    image_path: str | None,
    image_edit: dict | None,
    chat_messages: list[dict[str, str]] | None,
    conversations: list[dict] | None,
    current_conv_id: str,
):
    user_message = (user_message or "").strip()
    final_image_path = _extract_edited_image_path(image_edit) or image_path
    convs = [_normalize_conversation(c) for c in list(conversations or [])]
    if not convs:
        convs, current_conv_id = _load_or_init_conversations()

    current_conv = _find_conversation(convs, current_conv_id)
    agent_history = list(current_conv.get("messages", []))
    if not user_message and not final_image_path:
        yield (
            chat_messages or _history_to_chat_messages(agent_history),
            convs,
            current_conv_id,
            "",
            None,
            None,
            None,
            _render_history_sidebar(convs, current_conv_id),
        )
        return

    thinking_messages = list(chat_messages or [])
    user_display = user_message or "请识别并分析这张图片。"
    if final_image_path:
        user_display = f"{user_display}\n[已上传图片]"
    thinking_messages.append({"role": "user", "content": user_display})
    thinking_messages.append({"role": "assistant", "content": "<div class='ai-thinking'>思考中...</div>"})
    yield thinking_messages, convs, current_conv_id, user_message, image_path, image_edit, final_image_path, _render_history_sidebar(convs, current_conv_id)

    yield _submit_message(user_message, image_path, image_edit, chat_messages, convs, current_conv_id)


def _handle_history_action(
    action: str,
    target_id: str,
    payload: str,
    conversations: list[dict] | None,
    current_conv_id: str,
) -> tuple[str, list[dict], str, list[dict[str, str]], str]:
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
        return _render_history_sidebar(convs, active_id), convs, active_id, _history_to_chat_messages(selected.get("messages", [])), ""

    if not target_id:
        active = _find_conversation(convs, current_conv_id)
        return _render_history_sidebar(convs, current_conv_id), convs, current_conv_id, _history_to_chat_messages(active.get("messages", [])), ""

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
    return _render_history_sidebar(convs, current_conv_id), convs, current_conv_id, _history_to_chat_messages(active.get("messages", [])), ""


def _new_chat(conversations: list[dict]) -> tuple[str, list[dict], str, list[dict[str, str]], str]:
    convs = [_normalize_conversation(c) for c in list(conversations or [])]
    conv = _new_conversation([])
    convs.append(conv)
    active_id = conv["id"]
    _persist_conversations(convs, active_id)
    return _render_history_sidebar(convs, active_id), convs, active_id, [], ""


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
        if (btn) btn.click();
      };

      window.__historyAction = (action, targetId) => {
        document.querySelectorAll(".history-menu.open").forEach((menu) => menu.classList.remove("open"));
        if (action === "delete") {
          const ok = window.confirm("确定删除这条历史对话吗？");
          if (!ok) return;
        }
        dispatchHistoryAction(action, targetId, "");
      };

      window.__historyRename = (targetId) => {
        document.querySelectorAll(".history-menu.open").forEach((menu) => menu.classList.remove("open"));
        const currentTitle = document.querySelector(`.history-item[data-conv-id="${targetId}"] .history-title`)?.innerText || "";
        const newTitle = window.prompt("输入新的会话名称", currentTitle);
        if (newTitle && newTitle.trim()) {
          dispatchHistoryAction("rename", targetId, newTitle.trim());
        }
      };

      window.__toggleHistoryMenu = (event, targetId) => {
        event.preventDefault();
        event.stopPropagation();
        const menu = document.getElementById(`history-menu-${targetId}`);
        if (!menu) return;
        const alreadyOpen = menu.classList.contains("open");
        document.querySelectorAll(".history-menu.open").forEach((node) => node.classList.remove("open"));
        if (!alreadyOpen) menu.classList.add("open");
      };

      document.addEventListener("click", (event) => {
        if (!event.target.closest(".history-menu-wrap")) {
          document.querySelectorAll(".history-menu.open").forEach((menu) => menu.classList.remove("open"));
        }
      });

      document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.closest("#add-image-btn")) {
          const fileInput = document.querySelector("#image-box input[type='file']");
          if (fileInput instanceof HTMLElement) fileInput.click();
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
                with gr.Row(elem_id="preview-row"):
                    with gr.Group(elem_id="preview-card"):
                        image_preview = gr.Image(
                            type="filepath",
                            label=None,
                            show_label=False,
                            interactive=False,
                            visible=False,
                            elem_id="image-preview",
                        )
                        with gr.Row(elem_id="preview-actions-row"):
                            preview_delete_btn = gr.Button("×", elem_id="preview-delete-btn", scale=0)
                    preview_path_box = gr.Textbox(value="", elem_id="preview-path-box", elem_classes="bridge-hidden")
                image_editor = gr.ImageEditor(
                    label="图片批注（可框选重点）",
                    visible=False,
                    type="filepath",
                    brush=gr.Brush(colors=["#ff4d4f", "#00e5ff", "#ffd700"], default_size=6),
                    elem_id="image-editor",
                )

                with gr.Row(elem_id="input-wrap"):
                    add_image_btn = gr.Button("+", elem_id="add-image-btn", scale=0)
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

        history_action = gr.Textbox(value="", elem_id="history-action-box", elem_classes="bridge-hidden")
        history_target = gr.Textbox(value="", elem_id="history-target-box", elem_classes="bridge-hidden")
        history_payload = gr.Textbox(value="", elem_id="history-payload-box", elem_classes="bridge-hidden")
        history_dispatch = gr.Button("dispatch", elem_id="history-dispatch", elem_classes="bridge-hidden")
        send_btn.click(
            fn=_submit_message_stream,
            inputs=[message_box, image_box, image_editor, chatbot, conversations_state, current_conv_id_state],
            outputs=[chatbot, conversations_state, current_conv_id_state, message_box, image_box, image_editor, image_preview, history_html],
        )
        image_box.change(
            fn=lambda path: (
                gr.update(value=path, visible=bool(path)),
                path or "",
                gr.update(visible=bool(path)),
                gr.update(visible=False),
            ),
            inputs=[image_box],
            outputs=[image_preview, preview_path_box, preview_delete_btn, image_editor],
            queue=False,
            show_progress="hidden",
        )
        preview_delete_btn.click(
            fn=lambda: (
                None,
                "",
                gr.update(value=None, visible=False),
                gr.update(visible=False),
                gr.update(value=None, visible=False),
            ),
            inputs=[],
            outputs=[image_box, preview_path_box, image_preview, preview_delete_btn, image_editor],
            queue=False,
            show_progress="hidden",
        )
        new_chat_btn.click(
            fn=_new_chat,
            inputs=[conversations_state],
            outputs=[history_html, conversations_state, current_conv_id_state, chatbot, message_box],
        )
        history_dispatch.click(
            fn=_handle_history_action,
            inputs=[history_action, history_target, history_payload, conversations_state, current_conv_id_state],
            outputs=[history_html, conversations_state, current_conv_id_state, chatbot, message_box],
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
    }
    #history-list {
        flex: 1 1 auto !important;
        min-height: 0 !important;
        overflow-y: auto !important;
        margin-bottom: 10px !important;
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
    #image-preview .tools button:nth-child(1),
    #image-preview [class*="tools"] button:nth-child(1) {
        display: none !important;
        pointer-events: none !important;
    }
    #image-editor {
        margin: 0 0 8px 0 !important;
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
    #input-wrap {
        margin-top: 6px !important;
        flex: 0 0 auto !important;
        position: relative !important;
        display: block !important;
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

