"""Conversation turn progression (§3). Drives a session: opening line, then one
user→AI exchange per POST /turn. Timeline timestamps are approximate (derived
from audio durations) — the precise timeline used for analysis comes from
synth_data; live turns just need a plausible ordering for latency stats."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session as OrmSession

from ..config import AUDIO_DIR
from ..constants import AI_VOICE, USER_VOICE
from ..models import Session, Turn
from ..situations import load_situation
from .llm import LLM
from .stt import STT
from .tts import TTS
from .types import Message

_TURN_GAP_MS = 600  # assumed think-time gap between AI end and user start


def _session_dir(session_id: str) -> Path:
    d = AUDIO_DIR / f"session_{session_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_duration_ms(path: Path) -> int:
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return int(info.frames / info.samplerate * 1000)
    except Exception:
        return 0


def _next_start_ms(db: OrmSession, session_id: str) -> int:
    last_end = 0
    for t in db.query(Turn).filter_by(session_id=session_id):
        if t.end_ts_ms:
            last_end = max(last_end, t.end_ts_ms)
    return last_end + _TURN_GAP_MS if last_end else 0


async def start_session(
    db: OrmSession,
    situation_id: str,
    goal_id: str,
    *,
    tts: TTS,
    parent_session_id: Optional[str] = None,
) -> dict:
    situation = load_situation(situation_id)  # raises KeyError if unknown
    session = Session(
        situation_id=situation_id, goal_id=goal_id, parent_session_id=parent_session_id
    )
    db.add(session)
    db.flush()

    opening_text = situation["opening_line"]
    out_path = _session_dir(session.id) / "turn_00_ai.wav"
    await tts.synthesize(opening_text, AI_VOICE, out_path)
    dur = _audio_duration_ms(out_path)
    db.add(
        Turn(
            session_id=session.id,
            turn_index=0,
            speaker="ai",
            audio_path=str(out_path),
            start_ts_ms=0,
            end_ts_ms=dur,
            transcript=opening_text,
        )
    )
    db.commit()
    return {"session": session, "opening_text": opening_text, "opening_audio_path": out_path}


def _history_messages(db: OrmSession, session_id: str) -> list[Message]:
    msgs: list[Message] = []
    for t in (
        db.query(Turn).filter_by(session_id=session_id).order_by(Turn.turn_index).all()
    ):
        role = "assistant" if t.speaker == "ai" else "user"
        text = t.transcript or ""
        if text:
            msgs.append(Message(role=role, content=text))
    return msgs


async def run_turn(
    db: OrmSession,
    session: Session,
    user_audio_path: Path,
    turn_index: int,
    *,
    stt: STT,
    llm: LLM,
    tts: TTS,
) -> dict:
    situation = load_situation(session.situation_id)

    # 1. transcribe the user's audio
    user_tr = await stt.transcribe(Path(user_audio_path), verbatim=False)
    user_dur = _audio_duration_ms(Path(user_audio_path))
    start = _next_start_ms(db, session.id)
    db.add(
        Turn(
            session_id=session.id,
            turn_index=turn_index,
            speaker="user",
            audio_path=str(user_audio_path),
            start_ts_ms=start,
            end_ts_ms=start + user_dur,
            transcript=user_tr.text,
            transcript_verbatim=user_tr.text,
        )
    )
    db.flush()

    # 2. AI reply from the full history under the situation persona
    messages = _history_messages(db, session.id)
    ai_text = await llm.chat(situation["ai_persona"], messages)

    # 3. synthesize AI audio
    ai_path = _session_dir(session.id) / f"turn_{turn_index + 1:02d}_ai.wav"
    await tts.synthesize(ai_text, AI_VOICE, ai_path)
    ai_start = (start + user_dur) + _TURN_GAP_MS
    db.add(
        Turn(
            session_id=session.id,
            turn_index=turn_index + 1,
            speaker="ai",
            audio_path=str(ai_path),
            start_ts_ms=ai_start,
            end_ts_ms=ai_start + _audio_duration_ms(ai_path),
            transcript=ai_text,
        )
    )
    db.commit()
    return {"ai_text": ai_text, "ai_audio_path": ai_path, "transcript": user_tr.text}
