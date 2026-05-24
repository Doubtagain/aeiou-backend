"""Situation catalog endpoint (§6).

v3: 카테고리 필터(`?category=interview` 등)를 지원한다. category/difficulty는
YAML에 기본 포함된다(없으면 emotional/1로 폴백 — Pydantic 기본값)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from ..schemas import GoalOptionOut, SituationCategory, SituationOut
from ..situations import load_all_situations

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
    )


@router.get("/situations", response_model=list[SituationOut])
def list_situations(
    category: Optional[SituationCategory] = Query(
        None, description="emotional | interview | presentation | business"
    ),
) -> list[SituationOut]:
    out = [_to_out(s) for s in load_all_situations()]
    if category is not None:
        out = [s for s in out if s.category == category]
    return out
