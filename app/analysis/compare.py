"""Retake comparison (§5.3 / H4). Quantitative diffs (SPM, filler, latency,
judge overall) are computed in code and handed to the LLM, which renders the
verdict and picks the better side."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import object_session

from ..models import RetakeComparison, SessionAnalysis
from .judge import _session_transcript

if TYPE_CHECKING:
    from ..conversation.llm import LLM

_JUDGE_FIELDS = [
    "flow_coherence",
    "flow_consistency",
    "flow_goal_alignment",
    "flow_avoidance",
    "topic_adherence",
    "recovery_score",
]
_QUANT_FIELDS = [
    "spm_mean",
    "filler_count",
    "filler_density",
    "latency_p50_ms",
    "silence_ratio",
    "tail_clarity",
]

COMPARE_SYSTEM = (
    "당신은 한국어 대화 코치다. 같은 상황·목표로 진행된 두 세션(베이스라인 vs 리테이크)을 "
    "비교해 어느 쪽이 더 나은지 판정한다. 제공된 정량 지표와 대화 내용을 함께 근거로 삼되, "
    "리테이크가 더 나으면 무엇이 어떻게 '개선'됐는지 구체적으로 서술하라."
)


def _get(obj: Any, key: str):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _judge_overall(analysis: Any) -> Optional[float]:
    vals = [v for k in _JUDGE_FIELDS if isinstance((v := _get(analysis, k)), (int, float))]
    return round(sum(vals) / len(vals), 3) if vals else None


def _fetch_analysis(session: Any) -> Optional[SessionAnalysis]:
    db = object_session(session)
    if db is None:
        return None
    return db.get(SessionAnalysis, session.id)


def _side_summary(analysis: Any) -> dict:
    out = {"judge_overall": _judge_overall(analysis)}
    for f in _QUANT_FIELDS:
        out[f] = _get(analysis, f)
    return out


async def compare_sessions(baseline: Any, retake: Any, llm: "LLM") -> RetakeComparison:
    b_an = _fetch_analysis(baseline)
    r_an = _fetch_analysis(retake)
    b_side = _side_summary(b_an)
    r_side = _side_summary(r_an)

    quant_diff = {}
    for f in ["judge_overall", *_QUANT_FIELDS]:
        bv, rv = b_side.get(f), r_side.get(f)
        delta = (rv - bv) if isinstance(bv, (int, float)) and isinstance(rv, (int, float)) else None
        quant_diff[f] = {"baseline": bv, "retake": rv, "delta": delta}

    payload = {
        "baseline": b_side,
        "retake": r_side,
        "quant_diff": quant_diff,
        "baseline_transcript": _session_transcript(baseline),
        "retake_transcript": _session_transcript(retake),
    }
    user = (
        "두 세션을 비교해 더 나은 쪽을 고르고 한국어 총평을 작성하라.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    schema = {
        "better_side": "'baseline' | 'retake' | 'tie' 중 하나",
        "verdict": "한국어 총평. 리테이크가 나으면 '개선'된 점을 명시",
        "diff_summary": "핵심 정량 차이를 담은 객체",
    }
    result = await llm.chat_json(COMPARE_SYSTEM, user, schema)

    better = (result or {}).get("better_side", "tie")
    if better not in {"baseline", "retake", "tie"}:
        better = "tie"
    return RetakeComparison(
        baseline_session_id=getattr(baseline, "id", None),
        retake_session_id=getattr(retake, "id", None),
        better_side=better,
        diff_summary=(result or {}).get("diff_summary") or quant_diff,
        llm_verdict=(result or {}).get("verdict", ""),
    )
