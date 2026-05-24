"""H4 — retake comparison catches a meaningful difference (§7.3).

같은 상황·목표로 bad/good 세션을 합성하고, bad→baseline, good→retake로 비교한다.
합격: better_side == "retake" 이고 verdict에 "개선"이 포함.

    python scripts/eval_retake_diff.py
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


async def main() -> None:
    print(f"(use_mocks={settings.use_mocks})")
    bad_id = await synth_session(SITUATION, GOAL, "bad", "data/audio/retake_baseline")
    good_id = await synth_session(SITUATION, GOAL, "good", "data/audio/retake_good")
    await run_analysis(bad_id)
    await run_analysis(good_id)

    with session_scope() as db:
        baseline = db.get(Session, bad_id)
        retake = db.get(Session, good_id)
        comparison = await compare_sessions(baseline, retake, get_llm())
        db.add(comparison)
        better, verdict, diff = (
            comparison.better_side,
            comparison.llm_verdict,
            comparison.diff_summary,
        )

    passed = better == "retake" and "개선" in (verdict or "")
    print("\n=== H4: retake difference ===")
    print(f"  baseline(bad)={bad_id[:8]}  retake(good)={good_id[:8]}")
    print(f"  better_side: {better}")
    print(f"  verdict: {verdict}")
    print(f"  H4 RESULT: {'PASS' if passed else 'FAIL'}")

    out = {
        "baseline_session_id": bad_id,
        "retake_session_id": good_id,
        "better_side": better,
        "verdict": verdict,
        "diff_summary": diff,
        "use_mocks": settings.use_mocks,
        "pass": passed,
    }
    path = RESULTS_DIR / "eval_retake_diff.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved → {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true")
    p.parse_args()
    asyncio.run(main())
