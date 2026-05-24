"""v3 Step 7: 사용자 자유 텍스트 → SituationConfig dict 생성.

검증된 dict는 `situations.insert_user_situation`로 DB(payload JSON)에 영속화된다.
일반 YAML 카탈로그와 동일 스키마이므로 load_situation/start_session/pipeline이
그대로 재사용한다.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..conversation.llm import LLM


_VALID_CATEGORIES = {"emotional", "interview", "presentation", "business"}
_REQUIRED_KEYS = {
    "title",
    "category",
    "ai_persona",
    "opening_line",
    "goal_options",
}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SLUG_SANITIZE = re.compile(r"[^a-z0-9_]+")


SITUATION_SYSTEM = (
    "당신은 한국어 말하기 코칭 시나리오 작가다. 사용자가 자유 텍스트로 묘사한 상황을 "
    "표준 SituationConfig dict로 변환한다. 결과는 일반 카탈로그(이별·면접 등)와 동일 스키마를 "
    "따라야 한다. ai_persona는 6~10줄 한국어 구어체로 작성하고, opening_line은 한 문장의 "
    "현실적인 한국어 발화로 적는다. goal_options는 2개로 충분하다."
)


def _slug_from_title(title: str) -> str:
    base = (title or "").strip().lower()
    # 한글/특수문자 제거 → 영문/숫자/언더스코어만 유지
    base = base.replace(" ", "_")
    base = _SLUG_SANITIZE.sub("_", base).strip("_")
    base = re.sub(r"_+", "_", base)
    if not _ID_RE.match(base):
        base = f"user_situation_{uuid.uuid4().hex[:8]}"
    return base[:64]


def _coerce_int(x: Any, default: int) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _normalize(payload: dict, *, fallback_category: Optional[str]) -> dict:
    """LLM 출력 + 필요 시 디폴트로 누락 필드 채움, 타입 강제."""
    if not isinstance(payload, dict):
        raise ValueError("LLM did not return a SituationConfig dict")

    missing = [k for k in _REQUIRED_KEYS if not payload.get(k)]
    if missing:
        raise ValueError(f"missing required fields in generated situation: {missing}")

    category = str(payload.get("category", "")).strip().lower()
    if category not in _VALID_CATEGORIES:
        category = fallback_category if fallback_category in _VALID_CATEGORIES else "emotional"

    goal_options = payload.get("goal_options") or []
    if not isinstance(goal_options, list) or not goal_options:
        raise ValueError("goal_options must be a non-empty list")
    normalized_goals: list[dict] = []
    seen_goal_ids: set[str] = set()
    for g in goal_options:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or _slug_from_title(g.get("label") or ""))
        if gid in seen_goal_ids or not gid:
            continue
        seen_goal_ids.add(gid)
        ef = g.get("eval_focus") or []
        if not isinstance(ef, list):
            ef = [str(ef)]
        normalized_goals.append(
            {
                "id": gid,
                "label": str(g.get("label") or gid),
                "eval_focus": [str(x) for x in ef],
            }
        )
    if not normalized_goals:
        raise ValueError("goal_options had no valid entries")

    dur = payload.get("duration_target_sec") or [120, 240]
    if not (isinstance(dur, list) and len(dur) == 2):
        dur = [120, 240]
    dur = [_coerce_int(dur[0], 120), _coerce_int(dur[1], 240)]

    sid = str(payload.get("id") or "").strip().lower()
    if not _ID_RE.match(sid):
        sid = _slug_from_title(payload["title"])

    return {
        "id": sid,
        "title": str(payload["title"]),
        "category": category,
        "difficulty": min(3, max(1, _coerce_int(payload.get("difficulty", 2), 2))),
        "ai_persona": str(payload["ai_persona"]),
        "opening_line": str(payload["opening_line"]),
        "duration_target_sec": dur,
        "answer_length_guideline_sec": (
            _coerce_int(payload["answer_length_guideline_sec"], 0) or None
            if payload.get("answer_length_guideline_sec") is not None
            else None
        ),
        "goal_options": normalized_goals,
        "target_phonemes": payload.get("target_phonemes") or [],
        "author": "user",
    }


async def generate_situation(
    user_description: str, category_hint: Optional[str], llm: "LLM"
) -> dict:
    """LLM에 사용자 설명 + 카테고리 힌트를 보여주고 SituationConfig dict를 받는다.

    Returns: YAML 호환 dict (id 포함). 호출자가 insert_user_situation으로 영속화.
    Raises: ValueError — 필수 필드 누락 또는 LLM이 dict를 못 만든 경우.
    """
    user_description = (user_description or "").strip()
    if not user_description:
        raise ValueError("description is empty")

    payload = {
        "description": user_description,
        "category_hint": category_hint,
        "valid_categories": sorted(_VALID_CATEGORIES),
    }
    user = (
        "다음 사용자 설명을 SituationConfig 한 개로 변환하라. "
        "id는 영문 snake_case로, category는 valid_categories 중 하나로.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    schema = {
        "situation": (
            "{id:str(snake_case), title:str, category:str(emotional|interview|presentation|business), "
            "difficulty:int(1~3), ai_persona:str(6~10줄), opening_line:str, "
            "duration_target_sec:[int,int], goal_options:[{id:str, label:str, eval_focus:[str]}], "
            "answer_length_guideline_sec:int|null}"
        )
    }
    res = await llm.chat_json(SITUATION_SYSTEM, user, schema)
    sit = (res or {}).get("situation")
    return _normalize(sit, fallback_category=category_hint)
