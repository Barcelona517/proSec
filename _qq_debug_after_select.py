import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
_, window = qq._connect()
target = qq._resolve_chat_control(window, "好望角 03.04", allow_fuzzy=False)
target.click_input()

rows = []
for ctrl in window.descendants():
    try:
        info = ctrl.element_info
        rect = ctrl.rectangle()
        rows.append(
            {
                "type": getattr(info, "control_type", "") or "",
                "name": (ctrl.window_text() or "")[:120],
                "auto_id": getattr(info, "automation_id", "") or "",
                "class_name": getattr(info, "class_name", "") or "",
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
            }
        )
    except Exception:
        pass

Path("_qq_after_select.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok")
