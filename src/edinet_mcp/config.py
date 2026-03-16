from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_base_url: str = "https://api.edinet-fsa.go.jp"
    user_agent: str = "edinet-mcp/0.1"
    timeout_seconds: float = 30.0
    cache_dir: Path = Path(".cache")
    download_dir: Path = Path("downloads")



def get_settings() -> Settings:
    api_key = os.getenv("EDINET_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("EDINET_API_KEY is not set. Put it in .env or environment variables.")

    base = os.getenv("EDINET_API_BASE_URL", "https://api.edinet-fsa.go.jp").strip() or "https://api.edinet-fsa.go.jp"
    ua = os.getenv("EDINET_USER_AGENT", "edinet-mcp/0.1").strip() or "edinet-mcp/0.1"

    timeout_raw = os.getenv("EDINET_TIMEOUT_SECONDS", "30").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError:
        timeout = 30.0

    cache_dir = Path(os.getenv("EDINET_CACHE_DIR", ".cache"))
    download_dir = Path(os.getenv("EDINET_DOWNLOAD_DIR", "downloads"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        api_key=api_key,
        api_base_url=base.rstrip("/"),
        user_agent=ua,
        timeout_seconds=timeout,
        cache_dir=cache_dir,
        download_dir=download_dir,
    )
