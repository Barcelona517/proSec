from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from tooling import Tool


def register_tools(registry) -> None:
    registry.register(
        Tool(
            name="append_local_note",
            description="Append a short note to local notes/reminders.txt in workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Note text to append."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=lambda args: _append_local_note(registry.root, args),
        )
    )


def _append_local_note(root: Path, args: dict[str, Any]) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        return json.dumps({"ok": False, "error": "text cannot be empty"}, ensure_ascii=False)

    notes_dir = root / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_file = notes_dir / "reminders.txt"
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {text}\n"
    with notes_file.open("a", encoding="utf-8") as f:
        f.write(line)

    return json.dumps(
        {
            "ok": True,
            "path": str(notes_file),
            "appended": line.strip(),
        },
        ensure_ascii=False,
    )
