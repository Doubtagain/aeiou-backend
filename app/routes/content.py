"""Situation catalog endpoint (§6)."""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas import GoalOptionOut, SituationOut
from ..situations import load_all_situations

router = APIRouter(tags=["content"])


@router.get("/situations", response_model=list[SituationOut])
def list_situations() -> list[SituationOut]:
    out: list[SituationOut] = []
    for s in load_all_situations():
        out.append(
            SituationOut(
                id=s["id"],
                title=s["title"],
                opening_line=s["opening_line"],
                duration_target_sec=s.get("duration_target_sec", [120, 180]),
                goal_options=[GoalOptionOut(**g) for g in s.get("goal_options", [])],
            )
        )
    return out
