from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def read_pdf_text(args: dict[str, Any]) -> str:
    """Extract text from PDF file, optionally with page range."""
    file_path = str(args["file_path"]).strip()
    start_page = int(args.get("start_page", 1))
    end_page = args.get("end_page")
    if end_page is not None:
        end_page = int(end_page)

    from config import WORKSPACE_ROOT

    full_path = WORKSPACE_ROOT / file_path
    if not full_path.exists():
        return json.dumps(
            {"ok": False, "error": f"文件不存在: {file_path}"}, ensure_ascii=False
        )

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(full_path))
        total_pages = len(reader.pages)

        if start_page < 1:
            start_page = 1
        if end_page is None:
            end_page = total_pages
        end_page = min(end_page, total_pages)

        pages_text: list[str] = []
        for i in range(start_page - 1, end_page):
            text = (reader.pages[i].extract_text() or "").strip()
            if text:
                pages_text.append(f"[Page {i + 1}]\n{text}")

        extracted = "\n\n".join(pages_text)
        return json.dumps(
            {
                "ok": True,
                "file": file_path,
                "total_pages": total_pages,
                "extracted_pages": f"{start_page}-{end_page}",
                "char_count": len(extracted),
                "content": extracted[:8000],
                "truncated": len(extracted) > 8000,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": f"PDF 读取失败: {exc}"}, ensure_ascii=False
        )