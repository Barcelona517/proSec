import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
attach = qq.attach_or_launch()
entries = qq.read_message_entries(limit=60)

Path("_qq_message_entries_named.json").write_text(
    json.dumps(
        {
            "attach": attach,
            "entries": entries,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print("ok")
