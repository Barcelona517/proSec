import json
from pathlib import Path

from qq_tools import QQAutomation


qq = QQAutomation()
qq.open_chat("雪糕 3.17")
entries = qq.read_message_entries(limit=60)
Path("_xuegao_entries.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok")
