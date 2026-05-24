"""Analysis / rewrites / comparison read endpoints (§6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from ..analysis.coaching_tips import generate_coaching_tips
from ..db import get_db
from ..models import RecommendedRewrite, RetakeComparison, Session, SessionAnalysis
from ..situations import load_situation
from ..schemas import (
    AnalysisOut,
    CoachingOut,
    CoachingTipOut,
    ComparisonOut,
    PendingOut,
    PronunciationOut,
    RewriteOut,
    WeakWordOut,
)

router = APIRouter(tags=["analysis"])


@router.get("/sessions/{session_id}/analysis")
def get_analysis(session_id: str, db: OrmSession = Depends(get_db)):
    row = db.get(SessionAnalysis, session_id)
    if row is None:
        return PendingOut()
    out = AnalysisOut.model_validate(row)
    out.status = "ready"
    out.session_id = session_id
    return out


@router.get("/sessions/{session_id}/rewrites", response_model=list[RewriteOut])
def get_rewrites(session_id: str, db: OrmSession = Depends(get_db)):
    return db.query(RecommendedRewrite).filter_by(session_id=session_id).all()


@router.get("/sessions/{session_id}/pronunciation", response_model=PronunciationOut)
def get_pronunciation(session_id: str, db: OrmSession = Depends(get_db)):
    """v3 차별 기능: 발음 분석 결과 — weak_words 리스트.

    파이프라인이 분석을 마쳤다면 pronunciation_payload에 저장된 값을 그대로 반환한다.
    분석 전이면 404.
    """
    row = db.get(SessionAnalysis, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    payload = row.pronunciation_payload or {}
    weak = payload.get("weak_words") or []
    return PronunciationOut(weak_words=[WeakWordOut(**w) for w in weak])


@router.get("/sessions/{session_id}/coaching", response_model=CoachingOut)
def get_coaching(session_id: str, db: OrmSession = Depends(get_db)):
    """v3: 규칙 기반 팁(`tips`)과 LLM 재작성(`rewrites`)을 함께 반환.

    `/rewrites`는 하위 호환을 위해 유지된다.
    """
    analysis = db.get(SessionAnalysis, session_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="no analysis yet")
    # category 조회: session → situation YAML/payload. 못 찾으면 None(=default 임계).
    category: str | None = None
    sess = db.get(Session, session_id)
    if sess is not None:
        try:
            category = load_situation(sess.situation_id).get("category")
        except KeyError:
            category = None
    tips = [
        CoachingTipOut(id=t.id, title=t.title, body=t.body)
        for t in generate_coaching_tips(analysis, category=category)
    ]
    rewrites = db.query(RecommendedRewrite).filter_by(session_id=session_id).all()
    return CoachingOut(
        tips=tips,
        rewrites=[RewriteOut.model_validate(r) for r in rewrites],
    )


@router.get("/comparisons/{retake_session_id}", response_model=ComparisonOut)
def get_comparison(retake_session_id: str, db: OrmSession = Depends(get_db)):
    row = (
        db.query(RetakeComparison)
        .filter_by(retake_session_id=retake_session_id)
        .order_by(RetakeComparison.created_at.desc())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no comparison for this session")
    return row
