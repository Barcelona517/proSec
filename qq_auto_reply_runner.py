from __future__ import annotations

import os
import time

from auto_reply import auto_reply_once, bootstrap_auto_reply_state


def _parse_chat_list() -> list[str]:
    raw = os.getenv("AUTO_REPLY_CHATS", "")
    chats = [item.strip() for item in raw.split(",") if item.strip()]
    deduped: list[str] = []
    for chat in chats:
        if chat not in deduped:
            deduped.append(chat)
    return deduped


def main() -> None:
    chats = _parse_chat_list()
    if not chats:
        raise SystemExit("AUTO_REPLY_CHATS is empty. Please configure one or more QQ chat names in .env.")

    interval = int(os.getenv("AUTO_REPLY_INTERVAL_SECONDS", "8"))
    limit = int(os.getenv("AUTO_REPLY_MESSAGE_LIMIT", "20"))
    dry_run = os.getenv("AUTO_REPLY_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
    bootstrap = os.getenv("AUTO_REPLY_BOOTSTRAP", "true").lower() in {"1", "true", "yes", "on"}

    print("QQ auto-reply runner started.")
    print(f"Watching chats: {chats}")
    print(f"Interval: {interval}s | limit: {limit} | dry_run: {dry_run} | bootstrap: {bootstrap}")

    if bootstrap:
        for chat in chats:
            result = bootstrap_auto_reply_state(chat, limit=limit)
            print(f"[bootstrap] {chat}: {result['status']}")

    while True:
        for chat in chats:
            try:
                result = auto_reply_once(chat, limit=limit, dry_run=dry_run)
                status = result.get("status", "unknown")
                if status == "replied":
                    print(f"[replied] {chat}: {result.get('reply', '')}")
                elif status == "drafted":
                    print(f"[drafted] {chat}: {result.get('reply', '')}")
                else:
                    print(f"[{status}] {chat}")
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"[error] {chat}: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
