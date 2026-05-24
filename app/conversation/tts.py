"""TTS adapter (§4): Protocol + real OpenAI impl (step 8) + silent-WAV Mock."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..config import settings

SAMPLE_RATE = 16000
_SEC_PER_CHAR = 0.09  # ~ Korean speaking pace for mock duration
_MIN_SEC = 0.6
# v3: 120s까지 허용해 interview(임계 60s) / presentation(90s) bad mock 세션에서도
# too_long_turn_count가 합리적으로 잡힌다. 실제 한국어 한 발화로는 거의 도달 못 함.
_MAX_SEC = 120.0


def mock_duration_sec(text: str) -> float:
    return max(_MIN_SEC, min(_MAX_SEC, len((text or "").strip()) * _SEC_PER_CHAR))


class TTS(Protocol):
    async def synthesize(self, text: str, voice: str, out_path: Path) -> None: ...


class OpenAITTS:
    """Real OpenAI gpt-4o-mini-tts adapter. Streams a WAV to disk so downstream
    soundfile-based metrics can read it directly."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        from openai import AsyncOpenAI

        self.model = model or settings.openai_tts_model
        self.client = AsyncOpenAI(api_key=api_key)

    async def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=voice,
            input=text,
            response_format="wav",
        ) as resp:
            await resp.stream_to_file(str(out_path))


class MockTTS:
    """Write a silent mono WAV whose length is proportional to text length."""

    async def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        import numpy as np
        import soundfile as sf

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        n = int(mock_duration_sec(text) * SAMPLE_RATE)
        sf.write(str(out_path), np.zeros(n, dtype="float32"), SAMPLE_RATE, subtype="PCM_16")


def get_tts() -> "TTS":
    if settings.use_mocks or not settings.openai_api_key:
        return MockTTS()
    return OpenAITTS(settings.openai_api_key, settings.openai_tts_model)
