"""H1 — LLM-judge consistency (§7.2).

합성 세션 1개 분석을 N회 반복(매 회 judge 3중 내부 호출도 새로). 각 차원 점수의
표준편차를 출력한다. 합격: 각 차원 표준편차 ≤ 0.7 (5점 척도).

    python scripts/eval_judge_variance.py --runs 5

NOTE: 실 API에서만 의미가 있다(judge temperature 0.4 → 분산 발생). --mock은 결정론적
이라 분산이 0이며 H1을 실제로 검증하지 않는다.
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

from app.analysis.judge import judge_variance_report  # noqa: E402
from app.analysis.pipeline import run_analysis  # noqa: E402
from app.config import RESULTS_DIR, settings  # noqa: E402

SITUATION, GOAL = "breakup_last_conversation", "clear_closure"
THRESHOLD = 0.7


async def main(runs: int) -> None:
    print(f"(use_mocks={settings.use_mocks}) analyzing 1 session × {runs} repeats…")
    sid = await synth_session(SITUATION, GOAL, "mixed", "data/audio/eval_variance")

    all_runs: list[dict] = []
    for k in range(runs):
        an = await run_analysis(sid)
        all_runs.extend(an.judge_runs["flow"])
        all_runs.extend(an.judge_runs["improv"])
        print(f"  repeat {k + 1}/{runs} done")

    report = judge_variance_report(all_runs, threshold=THRESHOLD)

    print(f"\n=== H1: judge variance over {report['n_runs']} judge calls/dim ===")
    for dim in sorted(report["per_dim_stdev"]):
        mean = report["per_dim_mean"][dim]
        sd = report["per_dim_stdev"][dim]
        flag = "OK" if sd <= THRESHOLD else "FAIL"
        print(f"  {dim:>16}: mean={mean:<6} stdev={sd:<6} [{flag}]")
    print(f"\n  max_stdev={report['max_stdev']}  threshold={THRESHOLD}")
    print(f"  H1 RESULT: {'PASS' if report['pass'] else 'FAIL'}")

    out = {"session_id": sid, "n_repeats": runs, "use_mocks": settings.use_mocks, "report": report}
    path = RESULTS_DIR / "eval_judge_variance.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved → {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--mock", action="store_true")
    args = p.parse_args()
    asyncio.run(main(args.runs))
