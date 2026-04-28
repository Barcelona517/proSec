import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
qq.open_chat("雪糕 3.17")
_, window = qq._connect()
rows = []
for ctrl in window.descendants(control_type="Text"):
    try:
        rect = ctrl.rectangle()
        rows.append(
            {
                "text": (ctrl.window_text() or "")[:200],
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
            }
        )
    except Exception:
        pass

Path("_xuegao_raw_texts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok")
