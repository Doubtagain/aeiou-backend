"""Full flow, once (§7.1).

good 세션 합성 → 분석 → bad 세션 합성 → 분석 → 비교(baseline=bad, retake=good).
콘솔에 모든 핵심 지표와 better_side를 출력하고 data/results/demo_run.json에 저장한다.

기본은 실 API. 오프라인 스모크는 --mock.

    python scripts/demo_run.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
if "--mock" in sys.argv:
    os.environ["USE_MOCKS"] = "1"

from synth_data import synth_session  # noqa: E402

from app.analysis.compare import compare_sessions  # noqa: E402
from app.analysis.pipeline import run_analysis  # noqa: E402
from app.config import RESULTS_DIR, settings  # noqa: E402
from app.conversation.llm import get_llm  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import Session  # noqa: E402

SITUATION, GOAL = "breakup_last_conversation", "clear_closure"


def _metrics(an) -> dict:
    return {
        "flow": {
            "coherence": an.flow_coherence,
            "consistency": an.flow_consistency,
            "goal_alignment": an.flow_goal_alignment,
            "avoidance": an.flow_avoidance,
            "vocab_mattr": an.vocab_mattr,
            "sentence_length_stdev": an.sentence_length_stdev,
        },
        "improv": {
            "latency_p50_ms": an.latency_p50_ms,
            "latency_p90_ms": an.latency_p90_ms,
            "filler_count": an.filler_count,
            "filler_density": an.filler_density,
            "topic_adherence": an.topic_adherence,
            "recovery_score": an.recovery_score,
        },
        "delivery": {
            "spm_mean": an.spm_mean,
            "spm_stdev": an.spm_stdev,
            "f0_mean": an.f0_mean,
            "f0_stdev": an.f0_stdev,
            "silence_ratio": an.silence_ratio,
            "tail_clarity": an.tail_clarity,
        },
    }


def _print(label: str, m: dict) -> None:
    print(f"\n=== {label} ===")
    for group, vals in m.items():
        print(f"  [{group}]")
        for k, v in vals.items():
            print(f"    {k:>22}: {v}")


async def main() -> None:
    print(f"(use_mocks={settings.use_mocks})")
    good_id = await synth_session(SITUATION, GOAL, "good", "data/audio/demo_good")
    good_an = await run_analysis(good_id)
    bad_id = await synth_session(SITUATION, GOAL, "bad", "data/audio/demo_bad")
    bad_an = await run_analysis(bad_id)

    good_m, bad_m = _metrics(good_an), _metrics(bad_an)

    with session_scope() as db:
        baseline = db.get(Session, bad_id)   # 망친 버전
        retake = db.get(Session, good_id)    # 다듬은 버전
        comparison = await compare_sessions(baseline, retake, get_llm())
        db.add(comparison)
        better, verdict = comparison.better_side, comparison.llm_verdict
        diff = comparison.diff_summary

    _print("GOOD (retake)", good_m)
    _print("BAD (baseline)", bad_m)
    print("\n=== COMPARISON (baseline=bad, retake=good) ===")
    print(f"  better_side: {better}")
    print(f"  verdict: {verdict}")

    out = {
        "use_mocks": settings.use_mocks,
        "good": {"session_id": good_id, "metrics": good_m},
        "bad": {"session_id": bad_id, "metrics": bad_m},
        "comparison": {"better_side": better, "verdict": verdict, "diff_summary": diff},
    }
    path = RESULTS_DIR / "demo_run.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved → {path}")


if __name__ == "__main__":
    argparse.ArgumentParser().parse_known_args()  # tolerate --mock
    asyncio.run(main())
