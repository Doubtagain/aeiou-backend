"""LLM-as-judge (§5.3, H1). Each judge runs n_runs times; we return per-dimension
mean AND stdev so judge variance can be measured.

IMPORTANT (H1): the real adapter must use a NON-zero temperature (0.3-0.5) — see
ClaudeLLM. With temperature 0 the variance collapses and H1 becomes vacuous.
The mock is deterministic (variance 0), which is fine for plumbing/tests.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..conversation.llm import LLM

FLOW_DIMENSIONS = ["coherence", "consistency", "goal_alignment", "avoidance"]
IMPROV_DIMENSIONS = ["topic_adherence", "recovery"]

JUDGE_SYSTEM = (
    "당신은 한국어 대화 코치이며, 평가 기준에 엄격하게 따른다. "
    "각 차원을 1~5점 정수 척도로 평가하되 5점은 최상, 1점은 최악을 뜻한다. "
    "근거 없는 후한 점수를 주지 말고, 제시된 대화 내용만으로 판단하라."
)

JUDGE_PROMPT_FLOW = (
    "다음 한국어 연습 대화에서 '사용자'의 표현 흐름을 평가하라.\n"
    "선택한 목표: {goal_label} (평가 포커스: {eval_focus})\n"
    "평가 차원(각 1~5점):\n"
    "- coherence: 말이 자연스럽게 이어지고 횡설수설하지 않는가\n"
    "- consistency: 주장과 태도가 대화 내내 일관적인가\n"
    "- goal_alignment: 위 목표와 포커스에 부합하게 말했는가\n"
    "- avoidance: 핵심을 회피하지 않고 정면으로 말했는가 (5=거의 회피 없음)\n"
)

JUDGE_PROMPT_IMPROV = (
    "다음 한국어 연습 대화에서 '사용자'의 즉흥 대응 능력을 평가하라.\n"
    "선택한 목표: {goal_label} (평가 포커스: {eval_focus})\n"
    "평가 차원(각 1~5점):\n"
    "- topic_adherence: 상대(AI)의 말에 적절히 반응하고 주제를 유지했는가\n"
    "- recovery: 말이 막히거나 흔들렸을 때 잘 수습했는가\n"
)


@dataclass
class JudgeResult:
    dimensions: list[str]
    runs: list[dict] = field(default_factory=list)
    mean: dict[str, Optional[float]] = field(default_factory=dict)
    stdev: dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
def _session_transcript(session: Any) -> str:
    if isinstance(session, str):
        return session
    turns = getattr(session, "turns", None)
    if not turns:
        return getattr(session, "transcript", "") or ""
    lines = []
    for t in sorted(turns, key=lambda x: getattr(x, "turn_index", 0)):
        who = "AI" if getattr(t, "speaker", None) == "ai" else "사용자"
        text = getattr(t, "transcript_verbatim", None) or getattr(t, "transcript", "") or ""
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _goal_context(session: Any) -> dict:
    sid = getattr(session, "situation_id", None)
    gid = getattr(session, "goal_id", None)
    if sid and gid:
        try:
            from ..situations import goal_for

            g = goal_for(sid, gid)
            return {"label": g.get("label", gid), "eval_focus": g.get("eval_focus", [])}
        except Exception:
            pass
    return {"label": gid or "목표", "eval_focus": []}


def _coerce_score(v: Any) -> Optional[float]:
    try:
        return max(1.0, min(5.0, float(v)))
    except (TypeError, ValueError):
        return None


def _summarize(dimensions: list[str], runs: list[dict]) -> JudgeResult:
    mean: dict[str, Optional[float]] = {}
    stdev: dict[str, float] = {}
    for d in dimensions:
        vals = [r[d] for r in runs if r.get(d) is not None]
        if not vals:
            mean[d], stdev[d] = None, 0.0
        else:
            mean[d] = round(statistics.fmean(vals), 3)
            stdev[d] = round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0
    return JudgeResult(dimensions=dimensions, runs=runs, mean=mean, stdev=stdev)


async def _run_judge(
    rubric: str, dimensions: list[str], session: Any, llm: "LLM", n_runs: int
) -> JudgeResult:
    transcript = _session_transcript(session)
    goal = _goal_context(session)
    head = rubric.format(
        goal_label=goal["label"], eval_focus=", ".join(goal["eval_focus"]) or "없음"
    )
    payload = {
        "transcript": transcript,
        "goal": goal["label"],
        "eval_focus": goal["eval_focus"],
        "dimensions": dimensions,
    }
    user = head + "\n입력:\n" + json.dumps(payload, ensure_ascii=False)
    schema = {
        "scores": "각 차원 이름을 키로, 1~5 숫자를 값으로 갖는 객체 (모든 차원 포함)",
        "comment": "한 줄 총평",
    }
    runs: list[dict] = []
    for _ in range(n_runs):
        res = await llm.chat_json(JUDGE_SYSTEM, user, schema)
        scores = (res or {}).get("scores", {}) or {}
        run = {d: _coerce_score(scores.get(d)) for d in dimensions}
        run["_comment"] = (res or {}).get("comment")
        runs.append(run)
    return _summarize(dimensions, runs)


async def judge_flow(session: Any, llm: "LLM", n_runs: int = 3) -> JudgeResult:
    return await _run_judge(JUDGE_PROMPT_FLOW, FLOW_DIMENSIONS, session, llm, n_runs)


async def judge_improv(session: Any, llm: "LLM", n_runs: int = 3) -> JudgeResult:
    return await _run_judge(JUDGE_PROMPT_IMPROV, IMPROV_DIMENSIONS, session, llm, n_runs)


def judge_variance_report(runs: list[dict], threshold: float = 0.7) -> dict:
    """H1 metric: per-dimension stdev across the supplied runs + pass/fail.

    `runs` is a list of {dimension: score} dicts (any keys starting with '_'
    are ignored). Passes when every dimension's stdev ≤ threshold."""
    dims = sorted({k for r in runs for k in r if not k.startswith("_")})
    per_dim_stdev: dict[str, float] = {}
    per_dim_mean: dict[str, float] = {}
    for d in dims:
        vals = [r[d] for r in runs if isinstance(r.get(d), (int, float))]
        if len(vals) >= 2:
            per_dim_stdev[d] = round(statistics.pstdev(vals), 4)
            per_dim_mean[d] = round(statistics.fmean(vals), 4)
        elif vals:
            per_dim_stdev[d] = 0.0
            per_dim_mean[d] = round(vals[0], 4)
    max_stdev = max(per_dim_stdev.values(), default=0.0)
    return {
        "n_runs": len(runs),
        "threshold": threshold,
        "per_dim_mean": per_dim_mean,
        "per_dim_stdev": per_dim_stdev,
        "max_stdev": round(max_stdev, 4),
        "pass": max_stdev <= threshold,
    }
