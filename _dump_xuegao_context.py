import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
attach_before = qq.attach_or_launch()
open_result = qq.open_chat("雪糕 3.17")
attach_after = qq.attach_or_launch()

rows = []
_, window = qq._connect()
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

payload = {
    "attach_before": attach_before,
    "open_result": open_result,
    "attach_after": attach_after,
    "texts": rows[:120],
}
Path("_xuegao_context.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok")
