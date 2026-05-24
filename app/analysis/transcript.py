"""Verbatim STT re-processing (§5.5 step 2).

Re-transcribes each user turn's audio in verbatim mode (keeping fillers /
disfluencies) and updates Turn.transcript_verbatim. Returns per-turn Transcripts
(text + word timestamps) for the filler stage. Falls back to the stored text
when STT yields nothing (e.g. silent mock audio)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..conversation.types import Transcript

if TYPE_CHECKING:
    from ..conversation.stt import STT


async def reprocess_verbatim(session: Any, stt: "STT") -> dict[str, Transcript]:
    out: dict[str, Transcript] = {}
    for t in getattr(session, "turns", []):
        if getattr(t, "speaker", None) != "user":
            continue
        result: Transcript | None = None
        path = getattr(t, "audio_path", None)
        if path and Path(path).exists():
            result = await stt.transcribe(Path(path), verbatim=True)
        if result and result.text:
            t.transcript_verbatim = result.text
            out[t.id] = result
        else:
            text = t.transcript_verbatim or t.transcript or ""
            out[t.id] = Transcript(text=text, words=[])
    return out
