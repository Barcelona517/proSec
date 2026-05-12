from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
import re
import shutil
import io
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

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

def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _download_text(url: str) -> str:
    data = _download_bytes(url)
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


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


def parse_skill_install_input(text: str) -> tuple[str, str | None]:
    raw = (text or "").strip()
    if not raw:
        raise SkillImportError("请输入要安装的 URL 或命令")

    if not re.search(r"\s", raw):
        return raw, None

    url_match = re.search(r"https?://\S+", raw)
    if url_match is None:
        raise SkillImportError("没有在输入内容里找到 URL")

    url = url_match.group(0).rstrip(")],.;:'\"")
    skill_name: str | None = None

    skill_match = re.search(r"(?:--skill(?:=|\s+)|-s\s+)([A-Za-z0-9_\-]+)", raw)
    if skill_match is not None:
        skill_name = skill_match.group(1).strip() or None

    return url, skill_name

def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
    for src in sorted(src_dir.rglob("*")):
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _resolve_markdown_skill_record(folder: Path, markdown_path: Path) -> SkillRecord:
    raw_text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    metadata, body = _parse_frontmatter(raw_text)
    name = metadata.get("name") or _extract_title(body) or folder.name
    description = metadata.get("description") or _extract_description(body)
    return SkillRecord(
        name=name,
        description=description or "",
        folder=folder,
        markdown_path=markdown_path,
        content=raw_text,
        metadata=metadata,
    )


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

    normalized_name = _slugify(name).lower()
    for existing in scan_skills():
        existing_name = _slugify(existing.name).lower()
        if existing_name == normalized_name or existing.folder.name.lower() == normalized_name:
            raise SkillImportError(f"skill 已存在：{existing.name}")

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


def _is_github_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower().endswith("github.com")


def _parse_github_path(url: str) -> tuple[str, str, str | None, str | None]:
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SkillImportError("GitHub URL 格式不正确")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    ref: str | None = None
    subpath: str | None = None
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        ref = parts[3]
        if len(parts) > 4:
            subpath = "/".join(parts[4:])
    return owner, repo, ref, subpath


def _github_archive_candidates(url: str) -> list[str]:
    owner, repo, ref, _subpath = _parse_github_path(url)
    if ref:
        return [f"https://github.com/{owner}/{repo}/archive/refs/heads/{ref}.zip"]
    return [
        f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip",
        f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip",
    ]


def _github_raw_candidates(url: str, skill_name: str | None = None) -> list[str]:
    owner, repo, ref, subpath = _parse_github_path(url)
    branches = [ref] if ref else ["main", "master"]
    paths: list[str] = []

    if subpath:
        normalized = _normalize_zip_path(subpath).strip("/")
        if normalized:
            paths.extend([normalized, f"{normalized}/SKILL.md"])
    elif skill_name:
        skill_slug = _slugify(skill_name).lower()
        paths.extend([
            f"skills/{skill_slug}/SKILL.md",
            f"skills/{skill_name}/SKILL.md",
            f"{skill_slug}/SKILL.md",
        ])

    candidates: list[str] = []
    for branch in branches:
        for rel_path in paths:
            candidates.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rel_path}")
    return candidates


def _normalize_zip_path(name: str) -> str:
    return name.replace("\\", "/").lstrip("/")


def _archive_relative_path(path: str, archive_root_name: str | None = None) -> Path:
    relative = Path(_normalize_zip_path(path))
    if archive_root_name and relative.parts and relative.parts[0] == archive_root_name:
        relative = Path(*relative.parts[1:]) if len(relative.parts) > 1 else Path()
    return relative


def _choose_zip_skill_prefix(zf: zipfile.ZipFile, skill_hint: str | None = None, subpath: str | None = None) -> str:
    hint = (skill_hint or "").strip().lower()
    subpath_norm = _normalize_zip_path(subpath or "").strip("/").lower()
    candidates: list[tuple[int, str]] = []

    for info in zf.infolist():
        if info.is_dir():
            continue
        normalized = _normalize_zip_path(info.filename)
        lower = normalized.lower()
        if subpath_norm and subpath_norm not in lower:
            continue
        path = Path(normalized)
        if path.name.upper() != "SKILL.md" and path.suffix.lower() not in {".md", ".markdown"}:
            continue
        parts = [part.lower() for part in path.parts]
        score = 0
        if path.name.upper() == "SKILL.md":
            score += 6
        if hint:
            if hint == path.parent.name.lower():
                score += 10
            if hint in parts:
                score += 4
            if hint in lower:
                score += 2
            if path.stem.lower() == hint:
                score += 3
        if subpath_norm and subpath_norm in lower:
            score += 2
        candidates.append((score, normalized))

    if not candidates:
        raise SkillImportError("压缩包里没有找到可安装的 skill 文件")

    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    best_score, best_file = candidates[0]
    if best_score <= 0:
        raise SkillImportError("压缩包里没有找到匹配的 skill 文件")
    return str(Path(best_file).parent).replace("\\", "/")


def _install_skill_from_markdown_text(markdown_text: str, preferred_name: str | None = None) -> tuple[Path, SkillRecord]:
    metadata, body = _parse_frontmatter(markdown_text)
    name = (preferred_name or metadata.get("name") or _extract_title(body) or "skill").strip()
    description = metadata.get("description") or _extract_description(body)

    target_folder = _unique_folder_name(name)
    target_folder.mkdir(parents=True, exist_ok=False)
    markdown_path = target_folder / "SKILL.md"
    markdown_path.write_text(_build_skill_markdown(name, description, body), encoding="utf-8")
    return target_folder, _resolve_markdown_skill_record(target_folder, markdown_path)


def install_skill_from_url(url: str, skill_name: str | None = None) -> tuple[Path, SkillRecord]:
    ensure_skill_root()
    source_url = (url or "").strip()
    preferred_name = (skill_name or "").strip() or None
    if not source_url:
        raise SkillImportError("请输入要安装的 URL")

    if _is_github_url(source_url):
        _owner, _repo, _ref, subpath = _parse_github_path(source_url)
        archive_candidates = _github_archive_candidates(source_url)
        last_error: Exception | None = None
        for archive_url in archive_candidates:
            try:
                archive_bytes = _download_bytes(archive_url)
                with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                    skill_prefix = _choose_zip_skill_prefix(zf, preferred_name, subpath)
                    if subpath:
                        normalized_subpath = _normalize_zip_path(subpath).strip("/")
                        if skill_prefix:
                            skill_prefix = f"{skill_prefix}/{normalized_subpath}" if normalized_subpath not in skill_prefix else skill_prefix
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_root = Path(temp_dir)
                        extracted_root = temp_root / "archive"
                        zf.extractall(extracted_root)
                        top_dirs = [p for p in extracted_root.iterdir() if p.is_dir()]
                        if not top_dirs:
                            raise SkillImportError("无法解压 GitHub archive")
                        repo_root = top_dirs[0]
                        target_source: Path | None = None
                        candidate_rel_paths: list[Path] = []
                        if subpath:
                            candidate_rel_paths.append(_archive_relative_path(subpath, repo_root.name))
                        if preferred_name:
                            skill_slug = _slugify(preferred_name)
                            candidate_rel_paths.extend(
                                [
                                    Path("skills") / skill_slug,
                                    Path("skills") / preferred_name,
                                    Path(skill_slug),
                                    Path(preferred_name),
                                ]
                            )
                        if skill_prefix:
                            candidate_rel_paths.append(_archive_relative_path(skill_prefix, repo_root.name))

                        seen_candidates: set[str] = set()
                        for rel_path in candidate_rel_paths:
                            rel_key = rel_path.as_posix()
                            if not rel_key or rel_key in seen_candidates:
                                continue
                            seen_candidates.add(rel_key)
                            candidate = repo_root / rel_path
                            if candidate.exists() and candidate.is_dir():
                                target_source = candidate
                                break

                        if target_source is None:
                            if subpath:
                                target_source = repo_root / _archive_relative_path(subpath, repo_root.name)
                            else:
                                target_source = repo_root / _archive_relative_path(skill_prefix, repo_root.name)
                        if not target_source.exists() or not target_source.is_dir():
                            raise SkillImportError(f"没有找到 skill 目录: {preferred_name or subpath or 'unknown'}")
                        markdowns = sorted(target_source.glob("*.md"), key=lambda p: p.name.lower())
                        markdown_path = next((p for p in markdowns if p.name.lower() == "skill.md"), None) or (markdowns[0] if markdowns else None)
                        if markdown_path is None:
                            raise SkillImportError("目标目录里没有 markdown skill 文件")

                        metadata, body = _parse_frontmatter(markdown_path.read_text(encoding="utf-8", errors="ignore"))
                        name = (preferred_name or metadata.get("name") or target_source.name).strip()
                        description = metadata.get("description") or _extract_description(body)
                        target_folder = _unique_folder_name(name)
                        target_folder.mkdir(parents=True, exist_ok=False)
                        _copy_tree(target_source, target_folder)
                        canonical_markdown = target_folder / "SKILL.md"
                        if markdown_path.name != "SKILL.md":
                            canonical_markdown.write_text(_build_skill_markdown(name, description, body), encoding="utf-8")
                        elif markdown_path.name == "SKILL.md" and markdown_path.parent != target_folder:
                            shutil.copy2(markdown_path, canonical_markdown)
                        record = _resolve_markdown_skill_record(target_folder, canonical_markdown)
                        return target_folder, record
            except (urllib.error.URLError, zipfile.BadZipFile, SkillImportError, OSError) as exc:
                last_error = exc
                continue
        raise SkillImportError(f"从 GitHub 安装 skill 失败：{last_error or 'unknown error'}")

    if source_url.lower().endswith(('.md', '.markdown')):
        text = _download_text(source_url)
        return _install_skill_from_markdown_text(text, preferred_name)

    if source_url.lower().endswith('.zip'):
        archive_bytes = _download_bytes(source_url)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            skill_prefix = _choose_zip_skill_prefix(zf, preferred_name)
            with tempfile.TemporaryDirectory() as temp_dir:
                extracted_root = Path(temp_dir) / "archive"
                zf.extractall(extracted_root)
                top_dirs = [p for p in extracted_root.iterdir() if p.is_dir()]
                if not top_dirs:
                    raise SkillImportError("无法解压 skill 压缩包")
                archive_root = top_dirs[0]
                candidate_rel_paths: list[Path] = []
                if preferred_name:
                    skill_slug = _slugify(preferred_name)
                    candidate_rel_paths.extend(
                        [
                            Path("skills") / skill_slug,
                            Path("skills") / preferred_name,
                            Path(skill_slug),
                            Path(preferred_name),
                        ]
                    )
                if skill_prefix:
                    candidate_rel_paths.append(_archive_relative_path(skill_prefix, archive_root.name))

                source_folder: Path | None = None
                seen_candidates: set[str] = set()
                for rel_path in candidate_rel_paths:
                    rel_key = rel_path.as_posix()
                    if not rel_key or rel_key in seen_candidates:
                        continue
                    seen_candidates.add(rel_key)
                    candidate = archive_root / rel_path
                    if candidate.exists() and candidate.is_dir():
                        source_folder = candidate
                        break

                if source_folder is None:
                    source_folder = archive_root / _archive_relative_path(skill_prefix, archive_root.name)
                if not source_folder.exists() or not source_folder.is_dir():
                    raise SkillImportError("压缩包里没有找到 skill 目录")
                markdowns = sorted(source_folder.glob("*.md"), key=lambda p: p.name.lower())
                markdown_path = next((p for p in markdowns if p.name.lower() == "skill.md"), None) or (markdowns[0] if markdowns else None)
                if markdown_path is None:
                    raise SkillImportError("目标目录里没有 markdown skill 文件")
                metadata, body = _parse_frontmatter(markdown_path.read_text(encoding="utf-8", errors="ignore"))
                name = (preferred_name or metadata.get("name") or source_folder.name).strip()
                description = metadata.get("description") or _extract_description(body)
                target_folder = _unique_folder_name(name)
                target_folder.mkdir(parents=True, exist_ok=False)
                _copy_tree(source_folder, target_folder)
                canonical_markdown = target_folder / "SKILL.md"
                if markdown_path.name != "SKILL.md":
                    canonical_markdown.write_text(_build_skill_markdown(name, description, body), encoding="utf-8")
                record = _resolve_markdown_skill_record(target_folder, canonical_markdown)
                return target_folder, record

    text = _download_text(source_url)
    return _install_skill_from_markdown_text(text, preferred_name)


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
        return "<div class='skill-empty'>还没有导入 skill。可以点右上角按钮添加。</div>"

    cards: list[str] = []
    for skill in skills:
        title = skill.name.strip() or skill.folder.name
        folder_name = escape(skill.folder.name)
        cards.append(
            "<div class='skill-card'>"
            f"<div class='skill-card-title'>{escape(title)}</div>"
            f"<button type='button' class='skill-card-delete' data-skill-delete='{folder_name}' title='删除 skill'>×</button>"
            "</div>"
        )

    return "<div class='skill-list'>" + "".join(cards) + "</div>"


def delete_skill_folder(folder_name: str) -> SkillRecord:
    root = ensure_skill_root()
    target_folder_name = (folder_name or "").strip()
    if not target_folder_name:
        raise SkillImportError("请选择要删除的 skill")

    target_folder = root / target_folder_name
    if not target_folder.exists() or not target_folder.is_dir():
        raise SkillImportError("找不到要删除的 skill")

    markdown_path = target_folder / "SKILL.md"
    if not markdown_path.exists():
        markdowns = sorted(target_folder.glob("*.md"), key=lambda p: p.name.lower())
        if markdowns:
            markdown_path = markdowns[0]

    record = _resolve_markdown_skill_record(target_folder, markdown_path) if markdown_path.exists() else SkillRecord(
        name=target_folder.name,
        description="",
        folder=target_folder,
        markdown_path=markdown_path,
        content="",
        metadata={},
    )
    shutil.rmtree(target_folder)
    return record
