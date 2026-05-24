"""Session lifecycle endpoints (§6): create, turn, end, retake."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session as OrmSession

from ..analysis.pipeline import analyze_and_compare
from ..config import settings
from ..conversation.llm import get_llm
from ..conversation.orchestrator import run_turn, start_session, _session_dir
from ..conversation.stt import get_stt
from ..conversation.tts import get_tts
from ..db import get_db
from ..models import Session as SessionModel
from ..schemas import (
    EndOut,
    RetakeIn,
    RetakeOut,
    SessionCreateIn,
    SessionCreateOut,
    TurnOut,
)
from ..situations import goal_for

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateOut)
async def create_session(body: SessionCreateIn, db: OrmSession = Depends(get_db)):
    try:
        goal_for(body.situation_id, body.goal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    res = await start_session(db, body.situation_id, body.goal_id, tts=get_tts())
    return SessionCreateOut(
        session_id=res["session"].id,
        opening_audio_url=settings.audio_url_for(res["opening_audio_path"]),
        opening_text=res["opening_text"],
    )


@router.post("/{session_id}/turn", response_model=TurnOut)
async def post_turn(
    session_id: str,
    turn_index: int = Form(...),
    audio: UploadFile = File(...),
    db: OrmSession = Depends(get_db),
):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")
    dest = _session_dir(session_id) / f"turn_{turn_index:02d}_user.wav"
    dest.write_bytes(await audio.read())
    res = await run_turn(
        db, session, dest, turn_index, stt=get_stt(), llm=get_llm(), tts=get_tts()
    )
    return TurnOut(
        ai_text=res["ai_text"],
        ai_audio_url=settings.audio_url_for(res["ai_audio_path"]),
        transcript=res["transcript"],
    )


@router.post("/{session_id}/end", response_model=EndOut)
async def end_session(
    session_id: str, background: BackgroundTasks, db: OrmSession = Depends(get_db)
):
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")
    session.ended_at = datetime.now(timezone.utc)
    ends = [t.end_ts_ms for t in session.turns if t.end_ts_ms]
    if ends:
        session.duration_sec = max(ends) / 1000.0
    db.commit()
    # analysis (and retake comparison) runs in the background; poll GET /analysis
    background.add_task(analyze_and_compare, session_id)
    return EndOut(analysis_job_id=session_id)


@router.post("/{session_id}/retake", response_model=RetakeOut)
async def retake(
    session_id: str, body: RetakeIn, db: OrmSession = Depends(get_db)
):
    parent = db.get(SessionModel, session_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="unknown session")
    res = await start_session(
        db, parent.situation_id, parent.goal_id, tts=get_tts(), parent_session_id=parent.id
    )
    return RetakeOut(new_session_id=res["session"].id)
