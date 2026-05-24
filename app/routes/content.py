"""Situation catalog endpoint (§6).

v3:
- ?category=<emotional|interview|presentation|business> 필터
- ?author=<official|user|all> 필터 (default: all)
- POST /situations/custom — 사용자 자유 텍스트 → 맞춤 SituationConfig (premium gate)
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..content.generator import generate_situation
from ..conversation.llm import get_llm
from ..db import get_db
from ..schemas import (
    CustomSituationIn,
    GoalOptionOut,
    SituationCategory,
    SituationOut,
)
from ..situations import (
    insert_user_situation,
    load_all_situations,
)

router = APIRouter(tags=["content"])


def _to_out(s: dict) -> SituationOut:
    return SituationOut(
        id=s["id"],
        title=s["title"],
        opening_line=s["opening_line"],
        duration_target_sec=s.get("duration_target_sec", [120, 180]),
        goal_options=[GoalOptionOut(**g) for g in s.get("goal_options", [])],
        category=s.get("category", "emotional"),
        difficulty=int(s.get("difficulty", 1)),
        author=s.get("author", "official"),
    )


def _premium_ok(x_premium: Optional[str]) -> bool:
    """X-Premium 헤더 또는 ENABLE_PREMIUM=1 이면 허용."""
    if settings.enable_premium:
        return True
    if x_premium is None:
        return False
    return x_premium.strip().lower() in {"1", "true", "yes", "on"}


def require_premium(x_premium: Optional[str] = Header(default=None, alias="X-Premium")):
    if not _premium_ok(x_premium):
        raise HTTPException(
            status_code=402,
            detail="premium feature; set X-Premium: true or ENABLE_PREMIUM=1",
        )
    return True


@router.get("/situations", response_model=list[SituationOut])
def list_situations(
    category: Optional[SituationCategory] = Query(
        None, description="emotional | interview | presentation | business"
    ),
    author: Literal["official", "user", "all"] = Query(
        "all", description="official | user | all (default: all)"
    ),
) -> list[SituationOut]:
    out = [_to_out(s) for s in load_all_situations()]
    if category is not None:
        out = [s for s in out if s.category == category]
    if author != "all":
        out = [s for s in out if s.author == author]
    return out


@router.post(
    "/situations/custom",
    response_model=SituationOut,
    dependencies=[Depends(require_premium)],
)
async def create_custom_situation(
    body: CustomSituationIn,
    db: OrmSession = Depends(get_db),
):
    """LLM이 사용자 설명을 SituationConfig로 변환 → DB(author='user')에 저장 → SituationOut 반환."""
    try:
        sit = await generate_situation(body.description, body.category_hint, llm=get_llm())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    insert_user_situation(db, sit)
    return _to_out(sit)
