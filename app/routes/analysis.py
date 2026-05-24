"""Analysis / rewrites / comparison read endpoints (§6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..models import RecommendedRewrite, RetakeComparison, SessionAnalysis
from ..schemas import AnalysisOut, ComparisonOut, PendingOut, RewriteOut

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
