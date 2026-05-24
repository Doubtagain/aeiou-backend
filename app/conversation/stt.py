"""STT adapter (§4): Protocol + real Whisper impl (step 8) + sidecar Mock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..config import settings
from .types import Transcript, Word


class STT(Protocol):
    async def transcribe(self, audio_path: Path, *, verbatim: bool = False) -> Transcript: ...


def _audio_duration_ms(audio_path: Path) -> int:
    try:
        import soundfile as sf

        info = sf.info(str(audio_path))
        return int(info.frames / info.samplerate * 1000)
    except Exception:
        return 0


def _even_words(text: str, total_ms: int) -> list[Word]:
    toks = text.split()
    if not toks:
        return []
    span = max(total_ms, len(toks) * 200)
    per = span / len(toks)
    return [
        Word(text=tok, start_ms=int(i * per), end_ms=int((i + 1) * per))
        for i, tok in enumerate(toks)
    ]


class WhisperSTT:
    """Real OpenAI Whisper adapter (whisper-1). Verbatim mode requests
    verbose_json + word timestamps; otherwise just the text."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        from openai import AsyncOpenAI

        self.model = model or settings.openai_stt_model
        self.client = AsyncOpenAI(api_key=api_key)

    async def transcribe(self, audio_path: Path, *, verbatim: bool = False) -> Transcript:
        path = Path(audio_path)
        with open(path, "rb") as fh:
            if verbatim:
                resp = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=fh,
                    language="ko",
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
                words = [
                    Word(text=w.word, start_ms=int(w.start * 1000), end_ms=int(w.end * 1000))
                    for w in (getattr(resp, "words", None) or [])
                ]
                return Transcript(
                    text=getattr(resp, "text", ""),
                    words=words,
                    language=getattr(resp, "language", "ko"),
                )
            resp = await self.client.audio.transcriptions.create(
                model=self.model, file=fh, language="ko"
            )
        return Transcript(text=getattr(resp, "text", "") or "", words=[])


class MockSTT:
    """Read a sidecar `<stem>.transcript.json` next to the audio.

    Sidecar shape: {"text": str, "text_verbatim": str?, "words": [{text,start_ms,end_ms}]?}
    Missing words are synthesized evenly across the audio duration. Missing
    sidecar yields an empty transcript (pipeline falls back to the stored text).
    """

    async def transcribe(self, audio_path: Path, *, verbatim: bool = False) -> Transcript:
        audio_path = Path(audio_path)
        sidecar = audio_path.with_name(audio_path.stem + ".transcript.json")
        if not sidecar.exists():
            return Transcript(text="", words=[])
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        text = data.get("text", "")
        if verbatim and data.get("text_verbatim"):
            text = data["text_verbatim"]
        if data.get("words"):
            words = [
                Word(text=w["text"], start_ms=int(w["start_ms"]), end_ms=int(w["end_ms"]))
                for w in data["words"]
            ]
        else:
            words = _even_words(text, _audio_duration_ms(audio_path))
        return Transcript(text=text, words=words, language=data.get("language", "ko"))


def get_stt() -> "STT":
    if settings.use_mocks or not settings.openai_api_key:
        return MockSTT()
    return WhisperSTT(settings.openai_api_key, settings.openai_stt_model)
