from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from auto_reply import auto_reply_once, generate_reply_for_chat, load_persona, read_qq_chat_messages
from qq_tools import QQAutomation, QQAutomationError

class ToolExecutionError(Exception):
    pass


def safe_resolve_path(root: Path, user_path: str) -> Path:
    candidate = (root / user_path).resolve() if not Path(user_path).is_absolute() else Path(user_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolExecutionError(f"路径越界: {candidate} 不在允许目录 {root} 内") from exc
    return candidate


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ToolRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._tools: dict[str, Tool] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        self.register(
            Tool(
                name="get_current_time",
                description="Get the current local time, or the current time for a specific UTC offset.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "utc_offset": {
                            "type": "string",
                            "description": "Optional UTC offset like +08:00 or -05:00.",
                        }
                    },
                    "additionalProperties": False,
                },
                handler=self._get_current_time,
            )
        )

        self.register(
            Tool(
                name="get_weather",
                description="Get the current weather and a short forecast for a location.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city or place name to query weather for.",
                        }
                    },
                    "required": ["location"],
                    "additionalProperties": False,
                },
                handler=self._get_weather,
            )
        )

        self.register(
            Tool(
                name="preview_qq_send_target",
                description="Preview which QQ chat would be selected for a send action before actually sending.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The target QQ contact or group name to preview.",
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self._preview_qq_send_target,
            )
        )
        self.register(
            Tool(
                name="read_persona_file",
                description="Read the latest persona file used for QQ auto-replies.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=self._read_persona_file,
            )
        )
        self.register(
            Tool(
                name="read_qq_chat_messages",
                description="Open a QQ chat and read its latest messages.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The target QQ contact or group name."},
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of messages to read, default 20.",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self._read_qq_chat_messages_tool,
            )
        )
        self.register(
            Tool(
                name="draft_qq_auto_reply",
                description="Read the latest persona and QQ chat messages, then draft a reply without sending.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The target QQ contact or group name."},
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of messages to use as context, default 20.",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self._draft_qq_auto_reply,
            )
        )
        self.register(
            Tool(
                name="auto_reply_qq_once",
                description="Read persona, inspect the latest QQ messages, and send one safe auto-reply if there is a new message.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The target QQ contact or group name."},
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of messages to use as context, default 20.",
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "If true, only generate the reply draft and do not send it.",
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self._auto_reply_qq_once,
            )
        )

        self.register(
            Tool(
                name="launch_or_attach_qq",
                description="Launch QQ or attach to an already-open QQ desktop window.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=self._launch_or_attach_qq,
            )
        )

        self.register(
            Tool(
                name="list_qq_chats",
                description="List recent QQ chats from the desktop client.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of chats to return, default 20.",
                            "minimum": 1,
                            "maximum": 50,
                        }
                    },
                    "additionalProperties": False,
                },
                handler=self._list_qq_chats,
            )
        )

        self.register(
            Tool(
                name="open_qq_chat",
                description="Open a QQ chat by contact or group name.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The target QQ contact or group name.",
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self._open_qq_chat,
            )
        )

        self.register(
            Tool(
                name="send_qq_message",
                description="Send a QQ message to a specified contact or group.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The target QQ contact or group name."},
                        "content": {"type": "string", "description": "The message to send."},
                        "confirmed_name": {
                            "type": "string",
                            "description": "Optional exact chat name returned by preview_qq_send_target.",
                        },
                    },
                    "required": ["name", "content"],
                    "additionalProperties": False,
                },
                handler=self._send_qq_message,
            )
        )

        self.register(
            Tool(
                name="read_qq_messages",
                description="Read visible messages from the current QQ chat window.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of messages to return, default 20.",
                            "minimum": 1,
                            "maximum": 100,
                        }
                    },
                    "additionalProperties": False,
                },
                handler=self._read_qq_messages,
            )
        )

        self.register(
            Tool(
                name="search_qq_contact",
                description="Search contacts or groups in QQ by keyword.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "Keyword to search in QQ."},
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of matching chats to return, default 10.",
                            "minimum": 1,
                            "maximum": 30,
                        },
                    },
                    "required": ["keyword"],
                    "additionalProperties": False,
                },
                handler=self._search_qq_contact,
            )
        )

        self.register(
            Tool(
                name="search_web",
                description="Search the web for a topic or keyword and return concise results.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The keyword, noun, or question to search for.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of search results to return, default 5.",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=self._search_web,
            )
        )

        self.register(
            Tool(
                name="list_files",
                description="列出指定目录下的文件与子目录",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "相对工作目录路径，默认 .",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                handler=self._list_files,
            )
        )

        self.register(
            Tool(
                name="read_text_file",
                description="读取文本文件内容",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "相对工作目录文件路径"},
                        "max_chars": {
                            "type": "integer",
                            "description": "最多返回字符数，默认 4000",
                            "minimum": 100,
                            "maximum": 20000,
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                handler=self._read_text_file,
            )
        )

        self.register(
            Tool(
                name="write_text_file",
                description="写入文本文件，可覆盖或追加",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "相对工作目录文件路径"},
                        "content": {"type": "string", "description": "要写入的文本内容"},
                        "mode": {
                            "type": "string",
                            "enum": ["overwrite", "append"],
                            "description": "overwrite 覆盖，append 追加",
                        },
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                handler=self._write_text_file,
            )
        )

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def all_for_openai(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, raw_arguments: str) -> str:
        if name not in self._tools:
            raise ToolExecutionError(f"未知工具: {name}")

        try:
            arguments = json.loads(raw_arguments or "{}")
            if not isinstance(arguments, dict):
                raise ToolExecutionError("工具参数必须是 JSON object")
        except json.JSONDecodeError as exc:
            raise ToolExecutionError(f"工具参数不是合法 JSON: {exc}") from exc

        return self._tools[name].handler(arguments)

    def _list_files(self, args: dict[str, Any]) -> str:
        rel_path = args.get("path", ".")
        path = safe_resolve_path(self.root, rel_path)
        if not path.exists():
            raise ToolExecutionError(f"路径不存在: {rel_path}")
        if not path.is_dir():
            raise ToolExecutionError(f"目标不是目录: {rel_path}")

        items = []
        for p in sorted(path.iterdir(), key=lambda x: x.name.lower()):
            kind = "dir" if p.is_dir() else "file"
            items.append({"name": p.name, "type": kind})
        return json.dumps({"path": str(path), "items": items}, ensure_ascii=False)

    def _read_text_file(self, args: dict[str, Any]) -> str:
        rel_path = args["path"]
        max_chars = int(args.get("max_chars", 4000))
        path = safe_resolve_path(self.root, rel_path)

        if not path.exists():
            raise ToolExecutionError(f"文件不存在: {rel_path}")
        if not path.is_file():
            raise ToolExecutionError(f"目标不是文件: {rel_path}")

        content = path.read_text(encoding="utf-8")
        clipped = content[:max_chars]
        return json.dumps(
            {
                "path": str(path),
                "content": clipped,
                "truncated": len(content) > len(clipped),
                "total_chars": len(content),
            },
            ensure_ascii=False,
        )

    def _write_text_file(self, args: dict[str, Any]) -> str:
        rel_path = args["path"]
        content = args["content"]
        mode = args.get("mode", "overwrite")

        path = safe_resolve_path(self.root, rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with path.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            path.write_text(content, encoding="utf-8")

        return json.dumps({"path": str(path), "mode": mode, "written_chars": len(content)}, ensure_ascii=False)

    def _get_current_time(self, args: dict[str, Any]) -> str:
        utc_offset = str(args.get("utc_offset", "") or "").strip()
        if utc_offset:
            tz = self._parse_utc_offset(utc_offset)
            now = datetime.now(tz)
            return json.dumps(
                {
                    "timezone_mode": "utc_offset",
                    "utc_offset": utc_offset,
                    "iso": now.isoformat(timespec="seconds"),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "weekday": now.strftime("%A"),
                },
                ensure_ascii=False,
            )

        now = datetime.now().astimezone()
        offset = now.strftime("%z")
        normalized_offset = f"{offset[:3]}:{offset[3:]}" if offset else ""
        return json.dumps(
            {
                "timezone_mode": "local",
                "utc_offset": normalized_offset,
                "iso": now.isoformat(timespec="seconds"),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "weekday": now.strftime("%A"),
            },
            ensure_ascii=False,
        )

    def _parse_utc_offset(self, value: str) -> timezone:
        match = __import__("re").fullmatch(r"([+-])(\d{2}):(\d{2})", value)
        if not match:
            raise ToolExecutionError("utc_offset 必须是类似 +08:00 或 -05:00 的格式。")
        sign, hours_str, minutes_str = match.groups()
        hours = int(hours_str)
        minutes = int(minutes_str)
        if hours > 23 or minutes > 59:
            raise ToolExecutionError("utc_offset 超出有效范围。")
        total_minutes = hours * 60 + minutes
        if sign == "-":
            total_minutes = -total_minutes
        return timezone(timedelta(minutes=total_minutes))

    def _search_web(self, args: dict[str, Any]) -> str:
        query = str(args["query"]).strip()
        max_results = int(args.get("max_results", 5))
        if not query:
            raise ToolExecutionError("search query cannot be empty")

        search_360_key = (
            os.getenv("SEARCH360_API_KEY")
            or os.getenv("QIHOO360_API_KEY")
            or os.getenv("AI360_API_KEY")
        )
        if search_360_key:
            return self._search_with_360(query, max_results, search_360_key)

        serper_key = os.getenv("SERPER_API_KEY")
        if serper_key:
            return self._search_with_serper(query, max_results, serper_key)

        return self._search_with_duckduckgo(query, max_results)

    def _search_with_360(self, query: str, max_results: int, api_key: str) -> str:
        payload = json.dumps(
            {
                "model": "360gpt-pro",
                "messages": [{"role": "user", "content": query}],
                "max_refer_search_items": max(1, min(max_results, 10)),
                "enable_corner_markers": True,
                "enable_web_page_safety": True,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.360.cn/v1/search/aisearch",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        data = self._load_json_response(request, "360 search")

        answer = self._extract_360_answer_text(data)
        results = self._extract_360_references(data, max_results)
        if not answer and not results:
            raise ToolExecutionError("360 搜索返回成功，但未解析到可用内容，请检查账号权限或返回格式。")

        return json.dumps(
            {
                "query": query,
                "provider": "360_aisearch",
                "answer": answer,
                "results": results,
                "raw": data,
            },
            ensure_ascii=False,
        )

    def _extract_360_answer_text(self, data: dict[str, Any]) -> str:
        candidates: list[str] = []

        if isinstance(data.get("answer"), str):
            candidates.append(str(data["answer"]))
        if isinstance(data.get("content"), str):
            candidates.append(str(data["content"]))
        if isinstance(data.get("output_text"), str):
            candidates.append(str(data["output_text"]))

        choices = data.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        candidates.append(content)
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and isinstance(item.get("text"), str):
                                candidates.append(item["text"])

        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    content = item.get("content")
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                candidates.append(part["text"])

        for text in candidates:
            text = text.strip()
            if text:
                return text
        return ""

    def _extract_360_references(self, data: dict[str, Any], max_results: int) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        possible_lists = [
            data.get("references"),
            data.get("refer_search_items"),
            data.get("search_results"),
            data.get("results"),
            data.get("items"),
        ]

        for items in possible_lists:
            if not isinstance(items, list):
                continue
            for item in items:
                if len(refs) >= max_results:
                    return refs
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("name") or "").strip()
                link = str(item.get("url") or item.get("link") or "").strip()
                snippet = str(
                    item.get("summary_ai")
                    or item.get("summary")
                    or item.get("snippet")
                    or item.get("text")
                    or ""
                ).strip()
                if title or link or snippet:
                    refs.append({"title": title, "link": link, "snippet": snippet})

        return refs

    def _search_with_serper(self, query: str, max_results: int, api_key: str) -> str:
        payload = json.dumps({"q": query, "num": max_results}).encode("utf-8")
        request = urllib.request.Request(
            "https://google.serper.dev/search",
            data=payload,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        data = self._load_json_response(request, "Serper")

        organic = data.get("organic", [])[:max_results]
        results = [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in organic
        ]
        return json.dumps(
            {
                "query": query,
                "provider": "serper",
                "answer_box": data.get("answerBox"),
                "knowledge_graph": data.get("knowledgeGraph"),
                "results": results,
            },
            ensure_ascii=False,
        )

    def _search_with_duckduckgo(self, query: str, max_results: int) -> str:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "0",
            }
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        data = self._load_json_response(request, "DuckDuckGo")

        results: list[dict[str, str]] = []
        abstract = str(data.get("AbstractText", "")).strip()
        abstract_url = str(data.get("AbstractURL", "")).strip()
        heading = str(data.get("Heading", "")).strip()
        if abstract:
            results.append(
                {
                    "title": heading or query,
                    "link": abstract_url,
                    "snippet": abstract,
                }
            )

        def collect_topics(items: list[Any]) -> None:
            for item in items:
                if len(results) >= max_results:
                    return
                if isinstance(item, dict) and "Topics" in item:
                    collect_topics(item.get("Topics", []))
                    continue
                if not isinstance(item, dict):
                    continue
                text = str(item.get("Text", "")).strip()
                link = str(item.get("FirstURL", "")).strip()
                if text:
                    title = text.split(" - ", 1)[0].split(" – ", 1)[0]
                    results.append({"title": title, "link": link, "snippet": text})

        collect_topics(data.get("RelatedTopics", []))

        if not results:
            raise ToolExecutionError(
                "没有搜到可用结果。你可以换个更完整的关键词，或在 .env 中配置 SEARCH360_API_KEY 使用 360 搜索。"
            )

        return json.dumps(
            {
                "query": query,
                "provider": "duckduckgo_instant_answer",
                "results": results[:max_results],
            },
            ensure_ascii=False,
        )

    def _load_json_response(self, request: urllib.request.Request, provider_label: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore").strip()
            except Exception:
                body = ""
            detail = f"{provider_label} request failed: HTTP {exc.code} {exc.reason}"
            if body:
                detail = f"{detail}; body={body[:300]}"
            raise ToolExecutionError(detail) from exc
        except urllib.error.URLError as exc:
            raise ToolExecutionError(f"{provider_label} request failed: {exc}") from exc

    def _get_weather(self, args: dict[str, Any]) -> str:
        location = str(args["location"]).strip()
        if not location:
            raise ToolExecutionError("location cannot be empty")

        geocode_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {
                "name": location,
                "count": 1,
                "language": "zh",
                "format": "json",
            }
        )
        geocode_request = urllib.request.Request(
            geocode_url,
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        geocode_data = self._load_json_response(geocode_request, "Open-Meteo geocoding")
        results = geocode_data.get("results") or []
        if not results:
            raise ToolExecutionError(f"没有找到地点 `{location}` 的天气位置。")

        place = results[0]
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude is None or longitude is None:
            raise ToolExecutionError("地理编码成功，但缺少经纬度信息。")

        weather_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 3,
            }
        )
        weather_request = urllib.request.Request(
            weather_url,
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        weather_data = self._load_json_response(weather_request, "Open-Meteo weather")

        current = weather_data.get("current", {})
        daily = weather_data.get("daily", {})
        forecast: list[dict[str, Any]] = []
        dates = daily.get("time") or []
        codes = daily.get("weather_code") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        rain = daily.get("precipitation_probability_max") or []
        for i in range(min(3, len(dates))):
            forecast.append(
                {
                    "date": dates[i],
                    "weather": self._weather_code_to_text(codes[i] if i < len(codes) else None),
                    "temp_max_c": tmax[i] if i < len(tmax) else None,
                    "temp_min_c": tmin[i] if i < len(tmin) else None,
                    "precipitation_probability_max": rain[i] if i < len(rain) else None,
                }
            )

        return json.dumps(
            {
                "location_query": location,
                "resolved_location": {
                    "name": place.get("name", ""),
                    "admin1": place.get("admin1", ""),
                    "country": place.get("country", ""),
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "current": {
                    "time": current.get("time"),
                    "temperature_c": current.get("temperature_2m"),
                    "apparent_temperature_c": current.get("apparent_temperature"),
                    "humidity_percent": current.get("relative_humidity_2m"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "precipitation_mm": current.get("precipitation"),
                    "weather": self._weather_code_to_text(current.get("weather_code")),
                    "is_day": current.get("is_day"),
                },
                "forecast": forecast,
                "provider": "open-meteo",
            },
            ensure_ascii=False,
        )

    def _weather_code_to_text(self, code: Any) -> str:
        mapping = {
            0: "晴",
            1: "大体晴",
            2: "局部多云",
            3: "阴",
            45: "雾",
            48: "冻雾",
            51: "小毛毛雨",
            53: "毛毛雨",
            55: "强毛毛雨",
            56: "冻毛毛雨",
            57: "强冻毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            66: "冻雨",
            67: "强冻雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "雪粒",
            80: "小阵雨",
            81: "阵雨",
            82: "强阵雨",
            85: "小阵雪",
            86: "强阵雪",
            95: "雷暴",
            96: "雷暴伴小冰雹",
            99: "雷暴伴强冰雹",
        }
        try:
            return mapping.get(int(code), f"未知天气代码 {code}")
        except Exception:
            return "未知"

    def _qq(self) -> QQAutomation:
        return QQAutomation()

    def _launch_or_attach_qq(self, args: dict[str, Any]) -> str:
        try:
            result = self._qq().attach_or_launch()
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps(result, ensure_ascii=False)

    def _preview_qq_send_target(self, args: dict[str, Any]) -> str:
        name = str(args["name"]).strip()
        try:
            result = self._qq().preview_send_targets(name)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps(result, ensure_ascii=False)

    def _read_persona_file(self, args: dict[str, Any]) -> str:
        return json.dumps({"persona": load_persona()}, ensure_ascii=False)

    def _read_qq_chat_messages_tool(self, args: dict[str, Any]) -> str:
        name = str(args["name"]).strip()
        limit = int(args.get("limit", 20))
        try:
            messages = read_qq_chat_messages(name, limit=limit)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps({"chat": name, "messages": messages}, ensure_ascii=False)

    def _draft_qq_auto_reply(self, args: dict[str, Any]) -> str:
        name = str(args["name"]).strip()
        limit = int(args.get("limit", 20))
        try:
            messages = read_qq_chat_messages(name, limit=limit)
            reply = generate_reply_for_chat(name, messages)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps({"chat": name, "reply": reply, "messages_used": len(messages)}, ensure_ascii=False)

    def _auto_reply_qq_once(self, args: dict[str, Any]) -> str:
        name = str(args["name"]).strip()
        limit = int(args.get("limit", 20))
        dry_run = bool(args.get("dry_run", False))
        try:
            result = auto_reply_once(name, limit=limit, dry_run=dry_run)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps(result, ensure_ascii=False)

    def _list_qq_chats(self, args: dict[str, Any]) -> str:
        limit = int(args.get("limit", 20))
        try:
            chats = self._qq().list_chats(limit=limit)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps({"chats": chats}, ensure_ascii=False)

    def _open_qq_chat(self, args: dict[str, Any]) -> str:
        name = str(args["name"]).strip()
        try:
            result = self._qq().open_chat(name)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps(result, ensure_ascii=False)

    def _send_qq_message(self, args: dict[str, Any]) -> str:
        name = str(args["name"]).strip()
        content = str(args["content"])
        confirmed_name = str(args.get("confirmed_name", "")).strip()
        try:
            result = self._qq().send_message(name, content, confirmed_name=confirmed_name)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps(result, ensure_ascii=False)

    def _read_qq_messages(self, args: dict[str, Any]) -> str:
        limit = int(args.get("limit", 20))
        try:
            messages = self._qq().read_messages(limit=limit)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps({"messages": messages}, ensure_ascii=False)

    def _search_qq_contact(self, args: dict[str, Any]) -> str:
        keyword = str(args["keyword"]).strip()
        limit = int(args.get("limit", 10))
        try:
            result = self._qq().search_contact(keyword=keyword, limit=limit)
        except QQAutomationError as exc:
            raise ToolExecutionError(str(exc)) from exc
        return json.dumps({"matches": result}, ensure_ascii=False)
