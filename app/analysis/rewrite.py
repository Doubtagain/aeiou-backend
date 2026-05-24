"""Improvement rewrites (§5.3, H3): find weak dimensions → pick the turns that
matter → ask the LLM for 2-3 goal-aligned rewrites with rationales."""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Optional

from ..models import RecommendedRewrite

if TYPE_CHECKING:
    from ..conversation.llm import LLM

_WEAK_THRESHOLD = 3.5
_MAX_TURNS = 5
_HANGUL = re.compile(r"[가-힣]")

# analysis field → human-readable weakness label
_DIM_LABELS = {
    "flow_coherence": "표현 흐름의 일관성",
    "flow_consistency": "입장의 일관성",
    "flow_goal_alignment": "목표 부합",
    "flow_avoidance": "회피하지 않기",
    "topic_adherence": "주제 유지",
    "recovery_score": "흔들림에서의 회복",
}

REWRITE_SYSTEM = (
    "당신은 한국어 표현 코치다. 사용자의 원래 의도와 어조는 유지하되, "
    "선택한 목표와 약점 차원에 더 부합하도록 발화를 다시 쓴다. "
    "각 버전에는 왜 더 나은지 한 줄 rationale을 단다. 군말과 회피 표현은 덜어낸다."
)


def _get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _weak_dimensions(analysis: Any) -> list[str]:
    scored: list[tuple[str, float]] = []
    for key in _DIM_LABELS:
        val = _get(analysis, key)
        if isinstance(val, (int, float)):
            scored.append((key, float(val)))
    if not scored:
        return list(_DIM_LABELS.values())[:2]
    weak = [k for k, v in scored if v < _WEAK_THRESHOLD]
    if not weak:
        weak = [k for k, _ in sorted(scored, key=lambda kv: kv[1])[:2]]
    return [_DIM_LABELS[k] for k in weak]


def _select_turns(session: Any) -> list[Any]:
    users = [
        t
        for t in getattr(session, "turns", [])
        if getattr(t, "speaker", None) == "user"
        and (getattr(t, "transcript_verbatim", None) or getattr(t, "transcript", None))
    ]
    users.sort(
        key=lambda t: len(_HANGUL.findall(
            getattr(t, "transcript_verbatim", None) or getattr(t, "transcript", "") or ""
        )),
        reverse=True,
    )
    return users[:_MAX_TURNS]


def _goal_label(session: Any) -> str:
    sid, gid = getattr(session, "situation_id", None), getattr(session, "goal_id", None)
    if sid and gid:
        try:
            from ..situations import goal_for

            return goal_for(sid, gid).get("label", gid)
        except Exception:
            pass
    return gid or "목표"


async def recommend_rewrites(
    session: Any, analysis: Any, llm: "LLM"
) -> list[RecommendedRewrite]:
    turns = _select_turns(session)
    if not turns:
        return []

    weak = _weak_dimensions(analysis)
    goal_label = _goal_label(session)
    payload = {
        "goal_label": goal_label,
        "weak_dimensions": weak,
        "turns": [
            {
                "turn_id": t.id,
                "text": (t.transcript_verbatim or t.transcript or ""),
            }
            for t in turns
        ],
    }
    user = (
        f"목표: {goal_label}\n약점 차원: {', '.join(weak)}\n"
        "아래 각 발화를 2~3가지 버전으로 다시 쓰고, 버전마다 rationale을 달라.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    schema = {
        "rewrites": (
            "[{source_turn_id, original_text, variants:[{text, rationale}]}] 배열. "
            "각 turn당 2~3개의 variants."
        )
    }
    result = await llm.chat_json(REWRITE_SYSTEM, user, schema)

    text_by_id = {t.id: (t.transcript_verbatim or t.transcript or "") for t in turns}
    out: list[RecommendedRewrite] = []
    for item in (result or {}).get("rewrites", []) or []:
        turn_id = item.get("source_turn_id")
        variants = item.get("variants") or []
        if not variants:
            continue
        out.append(
            RecommendedRewrite(
                session_id=getattr(session, "id", None),
                source_turn_id=turn_id,
                original_text=item.get("original_text") or text_by_id.get(turn_id, ""),
                rewrites=variants,
            )
        )
    return out
