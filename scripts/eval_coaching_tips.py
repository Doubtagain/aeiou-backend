"""H5 — 표준 코칭 카드가 합성 bad 세션에서 합리적으로 트리거된다 (§3.8).

emotional / interview / presentation 카테고리별로 bad 세션을 합성하고, 각 세션에
대해 generate_coaching_tips가 어떤 카드(들)를 트리거하는지 확인한다.

합격 기준 (MIGRATION §3.8):
  - bad emotional 세션 : `clear_ending` 또는 `lead_with_conclusion` 하나 이상 트리거
  - bad interview 세션 : `shorten_answer` 또는 `lead_with_conclusion` 트리거
  (presentation은 informational; 실 API에서 더 의미 있음)

    python scripts/eval_coaching_tips.py [--mock]

NOTE: `--mock`은 결정론적 합성 대화가 짧아 interview 카테고리 트리거가 어려울 수
있다. 실 API에서는 bad 페르소나가 길게 두서없이 말하므로 자연스럽게 트리거된다.
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

from app.analysis.coaching_tips import generate_coaching_tips  # noqa: E402
from app.analysis.pipeline import run_analysis  # noqa: E402
from app.config import RESULTS_DIR, settings  # noqa: E402

# (situation_id, goal_id, category, expected_tip_ids[pass-by-any])
SCENARIOS = [
    (
        "breakup_last_conversation", "clear_closure", "emotional",
        {"clear_ending", "lead_with_conclusion"},
    ),
    (
        "interview_behavioral", "structured_star", "interview",
        {"shorten_answer", "lead_with_conclusion"},
    ),
    (
        "presentation_pitch", "clear_problem_first", "presentation",
        {"clear_ending", "lead_with_conclusion", "shorten_answer"},  # informational
    ),
]


async def _one(situation_id: str, goal_id: str, category: str, expected: set[str]) -> dict:
    out_dir = f"data/audio/eval_coaching_{category}_bad"
    sid = await synth_session(situation_id, goal_id, "bad", out_dir)
    an = await run_analysis(sid)
    tips = generate_coaching_tips(an, category=category)
    fired = sorted(t.id for t in tips)
    passed_required = (category in {"emotional", "interview"}) and bool(set(fired) & expected)
    return {
        "situation_id": situation_id,
        "category": category,
        "session_id": sid,
        "fired_tips": fired,
        "expected_any_of": sorted(expected),
        "answer_length_sec_mean": an.answer_length_sec_mean,
        "too_long_turn_count": an.too_long_turn_count,
        "tail_clarity": an.tail_clarity,
        "flow_goal_alignment": an.flow_goal_alignment,
        "passed_required_check": passed_required,
        "required_category": category in {"emotional", "interview"},
    }


async def main() -> None:
    print(f"(use_mocks={settings.use_mocks})")
    results = []
    for sid, gid, cat, expected in SCENARIOS:
        is_required = cat in {"emotional", "interview"}
        try:
            r = await _one(sid, gid, cat, expected)
            results.append(r)
            print(
                f"  [{cat:>13}] tips={r['fired_tips']}  "
                f"len_mean={r['answer_length_sec_mean']}s  "
                f"too_long={r['too_long_turn_count']}  "
                f"tail={r['tail_clarity']}"
            )
        except Exception as exc:  # noqa: BLE001
            # 에러 레코드도 required_category 플래그를 유지해 PASS 판정에서 누락되지 않게 한다.
            # passed_required_check는 False로 강제 → 에러는 곧 실패.
            results.append(
                {
                    "situation_id": sid,
                    "category": cat,
                    "error": repr(exc),
                    "passed_required_check": False,
                    "required_category": is_required,
                }
            )
            print(f"  [{cat:>13}] ERROR: {exc}")

    required = [r for r in results if r.get("required_category")]
    passed = bool(required) and all(r.get("passed_required_check") for r in required)

    print("\n=== H5: coaching tips trigger reasonably on bad sessions ===")
    for r in required:
        flag = "PASS" if r.get("passed_required_check") else "FAIL"
        if "error" in r:
            print(f"  {r['category']:>13}: ERROR ({r['error'][:80]})  [{flag}]")
        else:
            print(
                f"  {r['category']:>13}: fired={r['fired_tips']}  "
                f"expected any of {r['expected_any_of']}  [{flag}]"
            )
    print(f"  H5 RESULT: {'PASS' if passed else 'FAIL'}")

    out = {
        "use_mocks": settings.use_mocks,
        "scenarios": results,
        "pass": bool(passed),
    }
    path = RESULTS_DIR / "eval_coaching_tips.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved → {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true")
    p.parse_args()
    asyncio.run(main())
