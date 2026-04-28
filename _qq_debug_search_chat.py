from __future__ import annotations

import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
_, window = qq._connect()
qq._focus_search_and_filter(window, "包身工")
visible = qq.list_chats(limit=50)

Path("_qq_search_baoshengong.json").write_text(
    json.dumps(
        {
            "window_title": qq._safe_window_text(window),
            "visible": visible,
            "preview": qq.preview_send_targets("包身工"),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print("ok")
