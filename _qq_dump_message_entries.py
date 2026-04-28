import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
entries = qq.read_message_entries(limit=40)
Path("_qq_message_entries.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok")
