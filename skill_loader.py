from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import importlib.util
import sys

import yaml

from tooling import Tool


@dataclass
class SkillSpec:
    """Parsed skill specification from skill.yaml."""

    name: str
    version: str
    author: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    instructions: str = ""
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    tools: list[Tool] = field(default_factory=list)


class SkillLoader:
    """Load skills from directories containing skill.yaml + handler.py."""

    @staticmethod
    def load_from_dir(skill_dir: Path) -> SkillSpec:
        spec_file = skill_dir / "skill.yaml"
        if not spec_file.exists():
            raise FileNotFoundError(f"skill.yaml not found in {skill_dir}")

        with open(spec_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ValueError(f"Invalid skill.yaml in {skill_dir}: must be a YAML mapping")

        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError(f"skill.yaml in {skill_dir} is missing 'name' field")

        spec = SkillSpec(
            name=name,
            version=str(raw.get("version", "0.1.0")),
            author=str(raw.get("author", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            tags=[str(t).strip() for t in raw.get("tags", []) or []],
            instructions=str(raw.get("instructions", "")).strip(),
            dependencies=raw.get("dependencies", {}) or {},
        )

        # Dynamically import handler.py
        handler_path = skill_dir / "handler.py"
        if handler_path.exists():
            module = SkillLoader._import_module(f"skill_{name}", handler_path)
            tool_defs = raw.get("tools", []) or []
            for tool_def in tool_defs:
                if not isinstance(tool_def, dict):
                    continue
                tool_name = tool_def.get("name", "")
                if not tool_name:
                    continue
                handler_func = getattr(module, tool_name, None)
                if handler_func is None:
                    print(
                        f"[SkillLoader] WARNING: handler '{tool_name}' not found in "
                        f"{handler_path}; skipping this tool."
                    )
                    continue
                # Wrap handler to catch exceptions and return JSON error
                wrapped = SkillLoader._wrap_handler(handler_func, tool_name)
                spec.tools.append(Tool(
                    name=f"{spec.name}.{tool_name}",
                    description=str(tool_def.get("description", "")).strip(),
                    input_schema=tool_def.get("parameters", {"type": "object", "properties": {}}),
                    handler=wrapped,
                ))
        else:
            print(f"[SkillLoader] WARNING: handler.py not found in {skill_dir}; no tools loaded.")

        return spec

    @staticmethod
    def _import_module(module_name: str, file_path: Path) -> Any:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _wrap_handler(handler: Callable, tool_name: str) -> Callable[[dict[str, Any]], str]:
        import json as _json

        def wrapped(args: dict[str, Any]) -> str:
            try:
                return handler(args)
            except Exception as exc:
                return _json.dumps(
                    {"ok": False, "error": f"工具 [{tool_name}] 执行异常: {exc}"},
                    ensure_ascii=False,
                )

        return wrapped

    @staticmethod
    def discover_skills(skills_root: Path) -> list[SkillSpec]:
        """Scan a directory for subdirectories containing skill.yaml and load them all."""
        specs: list[SkillSpec] = []
        if not skills_root.exists() or not skills_root.is_dir():
            return specs

        for entry in sorted(skills_root.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "skill.yaml").exists():
                continue
            try:
                spec = SkillLoader.load_from_dir(entry)
                specs.append(spec)
                print(f"[SkillLoader] Loaded skill: {spec.name} (v{spec.version}) — {len(spec.tools)} tool(s)")
            except Exception as exc:
                print(f"[SkillLoader] ERROR loading skill from {entry.name}: {exc}")

        return specs