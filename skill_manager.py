from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import shutil

from config import WORKSPACE_ROOT


SKILL_ROOT = WORKSPACE_ROOT / ".claude" / "skills"


@dataclass(frozen=True)
class SkillRecord:
    name: str
    description: str
    folder: Path
    markdown_path: Path
    content: str
    metadata: dict[str, str]


class SkillImportError(Exception):
    pass


def ensure_skill_root() -> Path:
    SKILL_ROOT.mkdir(parents=True, exist_ok=True)
    return SKILL_ROOT


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", text).strip("_")
    return slug or "skill"


def _unique_folder_name(base_name: str) -> Path:
    root = ensure_skill_root()
    candidate = root / _slugify(base_name)
    if not candidate.exists():
        return candidate
    for idx in range(2, 1000):
        numbered = root / f"{candidate.name}_{idx}"
        if not numbered.exists():
            return numbered
    raise SkillImportError("无法为 skill 创建唯一目录")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if len(lines) < 3:
        return {}, text

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, text

    meta: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in lines[1:end_idx]:
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^[A-Za-z0-9_\-]+\s*:", line):
            key, value = line.split(":", 1)
            current_key = key.strip().lower()
            meta[current_key] = value.strip().strip('"').strip("'")
            continue
        if current_key and line.startswith("  "):
            meta[current_key] = (meta[current_key] + "\n" + line.strip()).strip()

    body = "\n".join(lines[end_idx + 1 :]).strip()
    return meta, body


def _extract_title(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title
        return line[:48]
    return "Skill"


def _extract_description(body: str) -> str:
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", body) if segment.strip()]
    if not paragraphs:
        return ""
    first = paragraphs[0]
    first = re.sub(r"^#+\s*", "", first).strip()
    return first[:180]


def _find_markdown_source(files: list[Path]) -> Path | None:
    skill_md = next((path for path in files if path.name.lower() == "skill.md"), None)
    if skill_md is not None:
        return skill_md
    markdowns = [path for path in files if path.suffix.lower() in {".md", ".markdown"}]
    return markdowns[0] if markdowns else None


def _build_skill_markdown(name: str, description: str, body: str) -> str:
    lines = ["---", f'name: "{name}"']
    if description:
        lines.append(f'description: "{description}"')
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    return "\n".join(lines).strip() + "\n"


def import_skill_bundle(file_paths: list[str]) -> tuple[Path, SkillRecord]:
    ensure_skill_root()
    files = [Path(path) for path in file_paths if isinstance(path, str) and Path(path).exists() and Path(path).is_file()]
    if not files:
        raise SkillImportError("没有可导入的文件")

    source_markdown = _find_markdown_source(files)
    if source_markdown is None:
        raise SkillImportError("请上传包含 SKILL.md 的 skill 文件夹")

    raw_text = source_markdown.read_text(encoding="utf-8", errors="ignore")
    metadata, body = _parse_frontmatter(raw_text)
    name = metadata.get("name") or _extract_title(body) or source_markdown.stem
    description = metadata.get("description") or _extract_description(body)

    target_folder = _unique_folder_name(name)
    target_folder.mkdir(parents=True, exist_ok=False)

    canonical_markdown = target_folder / "SKILL.md"
    canonical_markdown.write_text(_build_skill_markdown(name, description, body), encoding="utf-8")

    for src in files:
        dst = target_folder / src.name
        if dst.name.lower() == "skill.md":
            continue
        if dst.exists():
            continue
        shutil.copy2(src, dst)

    record = SkillRecord(
        name=name,
        description=description or "",
        folder=target_folder,
        markdown_path=canonical_markdown,
        content=canonical_markdown.read_text(encoding="utf-8"),
        metadata=metadata,
    )
    return target_folder, record


def scan_skills() -> list[SkillRecord]:
    root = ensure_skill_root()
    records: list[SkillRecord] = []
    if not root.exists():
        return records

    for folder in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name.lower()):
        markdown_path = folder / "SKILL.md"
        if not markdown_path.exists():
            markdowns = sorted(folder.glob("*.md"), key=lambda p: p.name.lower())
            if markdowns:
                markdown_path = markdowns[0]
            else:
                continue
        try:
            raw_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        metadata, body = _parse_frontmatter(raw_text)
        name = metadata.get("name") or _extract_title(body) or folder.name
        description = metadata.get("description") or _extract_description(body)
        records.append(
            SkillRecord(
                name=name,
                description=description,
                folder=folder,
                markdown_path=markdown_path,
                content=raw_text,
                metadata=metadata,
            )
        )
    return records


def _tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}", text.lower()))
    return {token for token in tokens if token}


def match_skill(user_input: str, skills: list[SkillRecord] | None = None) -> SkillRecord | None:
    skills = skills if skills is not None else scan_skills()
    if not skills:
        return None

    text = user_input.lower().strip()
    if not text:
        return None

    best_skill: SkillRecord | None = None
    best_score = 0
    query_tokens = _tokenize(text)

    for skill in skills:
        score = 0
        name_lower = skill.name.lower()
        description_lower = skill.description.lower()

        if name_lower and name_lower in text:
            score += 6
        if skill.folder.name.lower() in text:
            score += 3
        for token in _tokenize(skill.name):
            if token in text:
                score += 2
        for token in _tokenize(skill.description):
            if token in query_tokens:
                score += 1
        if description_lower and description_lower in text:
            score += 2

        if score > best_score:
            best_score = score
            best_skill = skill

    return best_skill if best_score >= 2 else None


def build_skill_prompt(user_input: str) -> str:
    skills = scan_skills()
    if not skills:
        return ""

    lines = ["当前可用 skill 目录："]
    for skill in skills:
        description = skill.description.strip() or "无描述"
        lines.append(f"- {skill.name}: {description}")

    matched = match_skill(user_input, skills)
    if matched is not None:
        lines.append("")
        lines.append(f"已命中 skill: {matched.name}")
        lines.append("以下是该 skill 的完整内容，请严格遵循：")
        lines.append(matched.content.strip())
    else:
        lines.append("")
        lines.append("如果用户意图与上面的某个 skill 匹配，请优先加载并执行对应 skill 文件。")

    return "\n".join(lines).strip()


def render_skill_catalog_html(skills: list[SkillRecord] | None = None) -> str:
    skills = skills if skills is not None else scan_skills()
    if not skills:
        return "<div class='skill-empty'>还没有导入 skill。可以拖入 skill 文件夹，或点右上角按钮添加。</div>"

    cards: list[str] = []
    for skill in skills:
        title = skill.name.strip() or skill.folder.name
        desc = skill.description.strip() or "无描述"
        rel_path = skill.folder.relative_to(SKILL_ROOT).as_posix() if skill.folder.is_relative_to(SKILL_ROOT) else skill.folder.name
        cards.append(
            "<div class='skill-card'>"
            f"<div class='skill-card-title'>{title}</div>"
            f"<div class='skill-card-desc'>{desc}</div>"
            f"<div class='skill-card-path'>{rel_path}</div>"
            "</div>"
        )

    return "<div class='skill-list'>" + "".join(cards) + "</div>"
