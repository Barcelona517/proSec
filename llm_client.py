from __future__ import annotations

from openai import OpenAI
import os


def _build_generic_client(api_key_env: str, base_url_env: str, fallback_api_key_env: str = "", fallback_base_url_env: str = "") -> OpenAI:
    api_key = os.getenv(api_key_env) or (os.getenv(fallback_api_key_env) if fallback_api_key_env else None)
    if not api_key:
        raise RuntimeError(f"缺少 {api_key_env} 环境变量")

    base_url = os.getenv(base_url_env) or (os.getenv(fallback_base_url_env) if fallback_base_url_env else None)
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def build_client() -> OpenAI:
    return _build_generic_client("OPENAI_API_KEY", "OPENAI_BASE_URL")


def build_vision_client() -> OpenAI:
    return _build_generic_client(
        "VISION_API_KEY",
        "VISION_BASE_URL",
        fallback_api_key_env="OPENAI_API_KEY",
        fallback_base_url_env="OPENAI_BASE_URL",
    )
