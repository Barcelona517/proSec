from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import os
import re
import subprocess
import time


class QQAutomationError(Exception):
    pass


def _require_pywinauto():
    try:
        from pywinauto import Application  # type: ignore
        from pywinauto.findwindows import ElementNotFoundError  # type: ignore
        from pywinauto.keyboard import send_keys  # type: ignore
        return Application, ElementNotFoundError, send_keys
    except Exception as exc:  # noqa: BLE001
        raise QQAutomationError(
            "未安装 pywinauto。请先执行 `pip install -r requirements.txt` 安装 QQ 自动化依赖。"
        ) from exc


def _require_win32gui():
    try:
        import win32gui  # type: ignore
        import win32process  # type: ignore
        return win32gui, win32process
    except Exception as exc:  # noqa: BLE001
        raise QQAutomationError("未安装 pywin32，无法枚举 QQ 窗口。") from exc


def _require_win32clipboard():
    try:
        import win32clipboard  # type: ignore
        import win32con  # type: ignore
        return win32clipboard, win32con
    except Exception as exc:  # noqa: BLE001
        raise QQAutomationError("未安装 pywin32，无法使用剪贴板发送中文消息。") from exc


@dataclass
class QQChatItem:
    name: str
    control_type: str
    automation_id: str


class QQAutomation:
    def __init__(self) -> None:
        self.title_re = os.getenv("QQ_WINDOW_TITLE_RE", ".*QQ.*")
        self.qq_exe_path = os.getenv("QQ_EXE_PATH", "").strip()
        self.backend = os.getenv("QQ_AUTOMATION_BACKEND", "uia")

    def attach_or_launch(self) -> dict[str, Any]:
        app, window = self._connect()
        return {
            "ok": True,
            "window_title": self._safe_window_text(window),
            "backend": self.backend,
            "launched": bool(getattr(app, "_started_by_us", False)),
        }

    def list_chats(self, limit: int = 20) -> list[dict[str, str]]:
        _, window = self._connect()
        items = self._collect_chat_items(window)
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in items:
            if item.name in seen:
                continue
            seen.add(item.name)
            results.append(
                {
                    "name": item.name,
                    "control_type": item.control_type,
                    "automation_id": item.automation_id,
                }
            )
            if len(results) >= limit:
                break
        return results

    def preview_send_targets(self, name: str) -> dict[str, Any]:
        _, window = self._connect()
        visible = self.list_chats(limit=50)
        candidates = self._match_chat_names(visible, name)
        return {
            "query": name,
            "visible_candidates": candidates[:10],
            "can_send_safely": len(candidates) == 1,
            "selected_name": candidates[0] if len(candidates) == 1 else "",
        }

    def open_chat(self, name: str) -> dict[str, Any]:
        _, window = self._connect()
        target = self._resolve_chat_control(window, name, allow_fuzzy=True)
        try:
            self._activate_chat(window, target, name)
        except Exception as exc:  # noqa: BLE001
            raise QQAutomationError(f"打开 QQ 会话失败: {exc}") from exc
        return {"ok": True, "opened_chat": name}

    def send_message(self, name: str, content: str, confirmed_name: str = "") -> dict[str, Any]:
        if not content.strip():
            raise QQAutomationError("消息内容不能为空。")

        _, window = self._connect()
        exact_name = confirmed_name.strip() or self._resolve_single_chat_name(window, name)
        target = self._resolve_chat_control(window, exact_name, allow_fuzzy=False)
        self._activate_chat(window, target, exact_name)
        self._ensure_safe_foreground(window, exact_name)

        editor = self._find_message_editor(window)
        try:
            if editor is not None:
                editor.set_focus()
                self._ensure_safe_foreground(window, exact_name)
                self._paste_text(content)
            else:
                input_area = self._find_input_area(window)
                input_area.click_input()
                time.sleep(0.2)
                self._ensure_safe_foreground(window, exact_name)
                self._paste_text(content)
            time.sleep(0.2)
            self._ensure_safe_foreground(window, exact_name)
            send_button = self._find_send_button(window)
            if send_button is not None:
                send_button.click_input()
            else:
                _, _, send_keys = _require_pywinauto()
                send_keys("{ENTER}")
        except Exception as exc:  # noqa: BLE001
            raise QQAutomationError(f"发送 QQ 消息失败: {exc}") from exc
        return {"ok": True, "chat": exact_name, "sent_chars": len(content)}

    def read_messages(self, limit: int = 20) -> list[str]:
        _, window = self._connect()
        texts: list[str] = []
        try:
            for ctrl in window.descendants(control_type="Text"):
                text = self._safe_window_text(ctrl).strip()
                if text and len(text) <= 500:
                    texts.append(text)
        except Exception as exc:  # noqa: BLE001
            raise QQAutomationError(f"读取 QQ 消息失败: {exc}") from exc
        deduped: list[str] = []
        for text in texts:
            if text not in deduped:
                deduped.append(text)
        return deduped[-limit:]

    def search_contact(self, keyword: str, limit: int = 10) -> list[dict[str, str]]:
        _, window = self._connect()
        self._focus_search_and_filter(window, keyword)
        time.sleep(0.5)
        return self.list_chats(limit=limit)

    def _connect(self):
        Application, ElementNotFoundError, _ = _require_pywinauto()
        process_id, hwnd = self._find_best_qq_window()
        if process_id:
            try:
                app = Application(backend=self.backend).connect(process=process_id)
                setattr(app, "_started_by_us", False)
                window = app.window(handle=hwnd) if hwnd else app.top_window()
                window.wait("ready", timeout=10)
                return app, window
            except Exception:
                pass

        app = Application(backend=self.backend)
        try:
            app.connect(title_re=self.title_re, timeout=5)
            setattr(app, "_started_by_us", False)
            window = app.window(title_re=self.title_re)
            window.wait("ready", timeout=10)
            return app, window
        except ElementNotFoundError:
            if not self.qq_exe_path:
                raise QQAutomationError(
                    "未找到已打开的 QQ 主窗口，也没有配置 QQ_EXE_PATH。请先手动打开 QQ，或在 .env 中配置 QQ_EXE_PATH。"
                )
            try:
                app = Application(backend=self.backend).start(self.qq_exe_path)
                setattr(app, "_started_by_us", True)
                time.sleep(3)
                window = app.top_window()
                window.wait("ready", timeout=10)
                return app, window
            except Exception as exc:  # noqa: BLE001
                raise QQAutomationError(f"启动 QQ 失败: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise QQAutomationError(f"连接 QQ 主窗口失败: {exc}") from exc

    def _find_best_qq_window(self) -> tuple[int, int]:
        rows = self._get_qq_process_rows()
        if not rows:
            return 0, 0

        visible_windows = self._get_visible_windows_by_pid({row["pid"] for row in rows})
        candidates = []
        for row in rows:
            pid = row["pid"]
            for hwnd, title, class_name in visible_windows.get(pid, []):
                score = 0
                if title:
                    score += 3
                if class_name.lower().startswith("chrome_widgetwin"):
                    score += 2
                if row["main_handle"]:
                    score += 5
                candidates.append((score, pid, hwnd, title, class_name))

        if candidates:
            candidates.sort(reverse=True)
            _, pid, hwnd, _, _ = candidates[0]
            return pid, hwnd

        for row in rows:
            if row["main_handle"]:
                return row["pid"], row["main_handle"]
        return rows[0]["pid"], 0

    def _get_qq_process_rows(self) -> list[dict[str, Any]]:
        cmd = (
            "Get-Process QQ -ErrorAction SilentlyContinue | "
            "Select-Object Id,Path,MainWindowHandle,MainWindowTitle | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="ignore",
        )
        text = completed.stdout.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except Exception:
            return []

        rows = data if isinstance(data, list) else [data]
        parsed: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed.append(
                {
                    "pid": int(row.get("Id", 0) or 0),
                    "path": str(row.get("Path", "") or ""),
                    "main_handle": int(row.get("MainWindowHandle", 0) or 0),
                    "main_title": str(row.get("MainWindowTitle", "") or ""),
                }
            )
        return [row for row in parsed if row["pid"]]

    def _get_visible_windows_by_pid(self, pids: set[int]) -> dict[int, list[tuple[int, str, str]]]:
        win32gui, win32process = _require_win32gui()
        result: dict[int, list[tuple[int, str, str]]] = {pid: [] for pid in pids}

        def callback(hwnd, _extra):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pids:
                    return True
                title = win32gui.GetWindowText(hwnd) or ""
                class_name = win32gui.GetClassName(hwnd) or ""
                result.setdefault(pid, []).append((hwnd, title, class_name))
            except Exception:
                return True
            return True

        win32gui.EnumWindows(callback, None)
        return result

    def _collect_chat_items(self, window) -> list[QQChatItem]:
        candidates: list[QQChatItem] = []
        try:
            for ctrl in window.descendants():
                control_type = getattr(ctrl.element_info, "control_type", "") or ""
                if control_type not in {"ListItem", "TreeItem", "DataItem", "Text"}:
                    continue
                try:
                    rect = ctrl.rectangle()
                except Exception:
                    continue
                if not self._is_sidebar_chat_rect(rect):
                    continue
                text = self._safe_window_text(ctrl).strip()
                if not self._looks_like_chat_name(text):
                    continue
                automation_id = getattr(ctrl.element_info, "automation_id", "") or ""
                candidates.append(QQChatItem(name=text, control_type=control_type, automation_id=automation_id))
        except Exception as exc:  # noqa: BLE001
            raise QQAutomationError(f"读取 QQ 会话列表失败: {exc}") from exc
        if not candidates:
            raise QQAutomationError("没有识别到 QQ 会话列表。可能是 QQ 界面版本变化，需要调整自动化选择器。")
        return candidates

    def _match_chat_names(self, visible: list[dict[str, str]], query: str) -> list[str]:
        norm_query = query.strip().lower()
        names = [str(item.get("name", "")).strip() for item in visible if str(item.get("name", "")).strip()]
        exact = [name for name in names if name.lower() == norm_query]
        if exact:
            return exact
        fuzzy = [name for name in names if norm_query in name.lower()]
        return fuzzy

    def _resolve_single_chat_name(self, window, query: str) -> str:
        visible = self.list_chats(limit=50)
        matches = self._match_chat_names(visible, query)
        if len(matches) == 1:
            return matches[0]

        self._focus_search_and_filter(window, query)
        time.sleep(0.6)
        visible = self.list_chats(limit=50)
        matches = self._match_chat_names(visible, query)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = "、".join(matches[:6])
            raise QQAutomationError(f"找到多个可能匹配 `{query}` 的会话：{names}。请使用更精确的会话名。")
        raise QQAutomationError(f"没有精确找到会话 `{query}`。为避免误发，本次不会发送。")

    def _resolve_chat_control(self, window, name: str, allow_fuzzy: bool):
        norm_target = name.strip().lower()
        items = self._collect_chat_items(window)
        exact_matches = [item for item in items if item.name.lower() == norm_target]
        if len(exact_matches) == 1:
            chosen = exact_matches[0]
        elif len(exact_matches) > 1:
            raise QQAutomationError(f"找到了多个与 `{name}` 完全同名的 QQ 会话，为避免误发，本次已停止发送。")
        elif allow_fuzzy:
            fuzzy_matches = [item for item in items if norm_target in item.name.lower()]
            if len(fuzzy_matches) == 1:
                chosen = fuzzy_matches[0]
            elif len(fuzzy_matches) > 1:
                names = "、".join(item.name for item in fuzzy_matches[:5])
                raise QQAutomationError(f"找到了多个可能匹配 `{name}` 的会话：{names}。请提供更精确的会话名。")
            else:
                raise QQAutomationError(f"没有找到名称匹配 `{name}` 的 QQ 会话。")
        else:
            raise QQAutomationError(f"没有精确找到会话 `{name}`。为避免误发，本次不会发送。")

        for ctrl in window.descendants():
            try:
                rect = ctrl.rectangle()
            except Exception:
                continue
            if not self._is_sidebar_chat_rect(rect):
                continue
            text = self._safe_window_text(ctrl).strip()
            control_type = getattr(ctrl.element_info, "control_type", "") or ""
            if text == chosen.name and control_type == chosen.control_type:
                return ctrl
        raise QQAutomationError(f"找到了会话 `{chosen.name}`，但没有定位到可点击控件。")

    def _focus_search_and_filter(self, window, keyword: str) -> None:
        editors = window.descendants(control_type="Edit")
        if editors:
            search_box = min(editors, key=lambda ctrl: self._rect_distance_score(ctrl))
            search_box.set_focus()
            try:
                search_box.set_edit_text("")
            except Exception:
                pass
            search_box.set_edit_text(keyword)
            return

        try:
            _, _, send_keys = _require_pywinauto()
            window.set_focus()
            time.sleep(0.2)
            send_keys("^f")
            time.sleep(0.3)
            send_keys("^a{BACKSPACE}")
            time.sleep(0.2)
            send_keys(keyword, with_spaces=True)
        except Exception as exc:  # noqa: BLE001
            raise QQAutomationError(f"无法激活 QQ 搜索框: {exc}") from exc

    def _activate_chat(self, window, target, expected_chat: str) -> None:
        try:
            target.set_focus()
        except Exception:
            pass
        last_error = None
        for _ in range(3):
            try:
                target.click_input()
                time.sleep(0.45)
                if self._is_target_chat_active(window, expected_chat):
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error:
            raise QQAutomationError(f"点击会话 `{expected_chat}` 后未能确认切换成功: {last_error}")
        raise QQAutomationError(f"点击会话 `{expected_chat}` 后未能确认切换成功。")

    def _is_target_chat_active(self, window, expected_chat: str) -> bool:
        foreground = self._get_foreground_window_info()
        title = (foreground.get("title") or self._safe_window_text(window) or "").strip()
        return expected_chat in title

    def _rect_distance_score(self, ctrl) -> int:
        try:
            rect = ctrl.rectangle()
            return rect.left + rect.top
        except Exception:
            return 10**9

    def _is_sidebar_chat_rect(self, rect) -> bool:
        try:
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            return False
        width = right - left
        height = bottom - top
        if left > 520:
            return False
        if top < 340 or bottom > 1320:
            return False
        if width < 60 or height < 18:
            return False
        return True

    def _find_message_editor(self, window):
        editors = []
        for ctrl in window.descendants(control_type="Edit"):
            try:
                rect = ctrl.rectangle()
                if rect.width() > 200 and rect.height() > 40:
                    editors.append(ctrl)
            except Exception:
                continue
        return editors[-1] if editors else None

    def _find_input_area(self, window):
        send_button = self._find_send_button(window)
        send_rect = None
        if send_button is not None:
            try:
                send_rect = send_button.rectangle()
            except Exception:
                send_rect = None

        candidates = []
        for ctrl in window.descendants(control_type="Group"):
            try:
                rect = ctrl.rectangle()
                width = rect.width()
                height = rect.height()
                if width < 600 or height < 80:
                    continue
                if send_rect is not None:
                    if rect.bottom > send_rect.top + 10:
                        continue
                    if rect.top < send_rect.top - 420:
                        continue
                candidates.append((abs((send_rect.top if send_rect else rect.bottom) - rect.bottom), -(width * height), ctrl))
            except Exception:
                continue
        if not candidates:
            raise QQAutomationError("没有找到 QQ 消息输入区域。")
        candidates.sort()
        return candidates[0][2]

    def _find_send_button(self, window):
        try:
            buttons = window.descendants(control_type="Button")
        except Exception:
            return None
        for ctrl in buttons:
            if self._safe_window_text(ctrl).strip() == "发送":
                return ctrl
        return None

    def _ensure_safe_foreground(self, window, expected_chat: str) -> None:
        foreground = self._get_foreground_window_info()
        window_title = self._safe_window_text(window)

        if not foreground["is_qq"]:
            raise QQAutomationError("检测到你已切走 QQ 窗口，发送已中止，避免误发。")

        visible_title = foreground["title"] or window_title
        if expected_chat and expected_chat not in visible_title:
            raise QQAutomationError(
                f"检测到当前前台 QQ 会话不是目标 `{expected_chat}`，发送已中止，避免误发。当前窗口标题：{visible_title}"
            )

    def _get_foreground_window_info(self) -> dict[str, Any]:
        win32gui, win32process = _require_win32gui()
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        class_name = win32gui.GetClassName(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        qq_rows = self._get_qq_process_rows()
        qq_pids = {row["pid"] for row in qq_rows}
        return {
            "hwnd": hwnd,
            "title": title,
            "class_name": class_name,
            "pid": pid,
            "is_qq": pid in qq_pids,
        }

    def _paste_text(self, text: str) -> None:
        win32clipboard, win32con = _require_win32clipboard()
        _, _, send_keys = _require_pywinauto()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        send_keys("^v")

    def _looks_like_chat_name(self, text: str) -> bool:
        if not text or len(text) > 40:
            return False
        if text in {"QQ", "搜索", "消息", "联系人", "群聊", "发送"}:
            return False
        if text in {"[图片]", "[动画表情]"}:
            return False
        if text.endswith("："):
            return False
        if "撤回了一条消息" in text:
            return False
        if text.startswith("@") and len(text) > 6:
            return False
        if text.startswith("(") and text.endswith(")"):
            return False
        if any(p in text for p in ("哈哈", "真的吗", "真的", "啊？", "这下看懂了")) and len(text) <= 10:
            return False
        if re.fullmatch(r"[\d:\-\s]+", text):
            return False
        return True

    def _safe_window_text(self, ctrl) -> str:
        try:
            return str(ctrl.window_text() or "")
        except Exception:
            return ""
