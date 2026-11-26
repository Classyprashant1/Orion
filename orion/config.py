"""Configuration management for ORION Desktop Virtual Assistant."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class OrionConfig:
    """Immutable runtime configuration loaded from environment variables and `.env`."""

    project_root: Path
    db_path: Path
    screenshot_dir: Path
    api_host: str
    api_port: int
    auto_start_api: bool
    stt_language: str
    wake_word: str
    openweather_api_key: str
    default_city: str
    ai_provider: str
    gemini_api_key: str
    gemini_model: str
    openai_api_key: str
    openai_model: str

    @classmethod
    def load(cls, env_file: Path | None = None) -> "OrionConfig":
        """Load configuration from `.env` (if present) and OS environment variables."""
        target_env = env_file or (PROJECT_ROOT / ".env")
        if target_env.exists():
            load_dotenv(dotenv_path=target_env, override=False)

        def _resolve_path(raw: str, default_rel: str) -> Path:
            p = Path(raw or default_rel)
            return p if p.is_absolute() else (PROJECT_ROOT / p)

        def _parse_bool(raw: str | None, default: bool) -> bool:
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def _parse_int(raw: str | None, default: int) -> int:
            if not raw:
                return default
            try:
                return int(raw.strip())
            except ValueError:
                return default

        db_path = _resolve_path(os.getenv("ORION_DB_PATH", ""), "data/orion.db")
        screenshot_dir = _resolve_path(
            os.getenv("ORION_SCREENSHOT_DIR", ""), "screenshots"
        )
        db_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=PROJECT_ROOT,
            db_path=db_path,
            screenshot_dir=screenshot_dir,
            api_host=os.getenv("ORION_API_HOST", "127.0.0.1").strip() or "127.0.0.1",
            api_port=_parse_int(os.getenv("ORION_API_PORT"), 8765),
            auto_start_api=_parse_bool(os.getenv("ORION_AUTO_START_API"), True),
            stt_language=os.getenv("ORION_STT_LANGUAGE", "en-IN").strip() or "en-IN",
            wake_word=os.getenv("ORION_WAKE_WORD", "orion").strip().lower() or "orion",
            openweather_api_key=os.getenv("OPENWEATHER_API_KEY", "").strip(),
            default_city=os.getenv("ORION_DEFAULT_CITY", "Delhi").strip() or "Delhi",
            ai_provider=os.getenv("ORION_AI_PROVIDER", "none").strip().lower() or "none",
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
            or "gemini-2.0-flash",
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
            or "gpt-4o-mini",
        )
