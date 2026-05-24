"""Environment / path configuration.

Loads `.env` (if present) and exposes a single `settings` object. No external
service is contacted here — `USE_MOCKS=1` flips every adapter to its
deterministic mock so the whole app runs offline.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
RESULTS_DIR = DATA_DIR / "results"
CONTENT_DIR = BASE_DIR / "content"
SITUATIONS_DIR = CONTENT_DIR / "situations"


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
        self.use_mocks: bool = _as_bool(os.getenv("USE_MOCKS"))
        # v3: 사용자 맞춤 상황 생성 게이트(POST /situations/custom).
        # 헤더 X-Premium: true가 동일한 효과를 낸다 — 실 결제 모듈은 비범위.
        self.enable_premium: bool = _as_bool(os.getenv("ENABLE_PREMIUM"))

        self.anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.openai_stt_model: str = os.getenv("OPENAI_STT_MODEL", "whisper-1")
        self.openai_tts_model: str = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")

        self.database_url: str = os.getenv(
            "DATABASE_URL", f"sqlite:///{BASE_DIR / 'aeiou.db'}"
        )

        for d in (DATA_DIR, AUDIO_DIR, RESULTS_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def audio_url_for(self, path: str | Path) -> str:
        """Map an on-disk audio path under data/audio to its /static URL."""
        p = Path(path).resolve()
        try:
            rel = p.relative_to(AUDIO_DIR.resolve())
        except ValueError:
            return str(p)
        return "/static/audio/" + rel.as_posix()


settings = Settings()
