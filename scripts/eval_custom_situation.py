"""H6 — 사용자 맞춤 상황 생성이 사용 가능한 YAML을 만든다 (§3.8).

3가지 자연어 설명을 입력으로 generate_situation을 호출하고 각 결과가
  (a) 모든 필수 필드를 갖추고
  (b) opening_line과 ai_persona를 바탕으로 실제 대화 1턴까지 굴러가는지
확인한다.

합격 기준: 3개 중 3개 성공.

    python scripts/eval_custom_situation.py [--mock]
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

from app.config import RESULTS_DIR, settings  # noqa: E402
from app.content.generator import generate_situation  # noqa: E402
from app.conversation.llm import get_llm  # noqa: E402
from app.conversation.types import Message  # noqa: E402

DESCRIPTIONS = [
    ("백엔드 시니어 면접에서 시스템 설계 문제를 풀어야 한다", "interview"),
    ("오래된 친구의 결혼식 축사를 부담스러워하는데 준비해야 한다", "emotional"),
    ("팀장에게 연봉 협상을 위한 미팅을 요청해야 한다", "business"),
]

REQUIRED_FIELDS = [
    "id", "title", "category", "difficulty",
    "ai_persona", "opening_line", "duration_target_sec", "goal_options",
]


async def _drive_one_turn(sit: dict, llm) -> str:
    """opening_line이 주어진 상태에서 가상의 user 발화 1개에 대한 AI 응답을 받는다."""
    msgs = [
        Message(role="assistant", content=sit["opening_line"]),
        Message(role="user", content="네, 한번 같이 이야기 나눠 보겠습니다."),
    ]
    reply = await llm.chat(sit["ai_persona"], msgs)
    return (reply or "").strip()


async def _eval_one(desc: str, hint: str, llm) -> dict:
    record: dict = {"description": desc, "category_hint": hint}
    try:
        sit = await generate_situation(desc, hint, llm)
    except Exception as exc:  # noqa: BLE001
        record["error_generation"] = repr(exc)
        record["pass"] = False
        return record

    missing = [k for k in REQUIRED_FIELDS if not sit.get(k)]
    if missing:
        record["error_validation"] = f"missing fields: {missing}"
        record["pass"] = False
        return record

    try:
        ai_reply = await _drive_one_turn(sit, llm)
    except Exception as exc:  # noqa: BLE001
        record["error_dialogue"] = repr(exc)
        record["pass"] = False
        return record

    record.update(
        situation_id=sit["id"],
        category=sit["category"],
        title=sit["title"],
        ai_reply_preview=ai_reply[:60],
        ai_reply_nonempty=bool(ai_reply),
    )
    record["pass"] = bool(ai_reply)
    return record


async def main() -> None:
    print(f"(use_mocks={settings.use_mocks})")
    llm = get_llm()
    results = []
    for desc, hint in DESCRIPTIONS:
        r = await _eval_one(desc, hint, llm)
        results.append(r)
        flag = "PASS" if r.get("pass") else "FAIL"
        print(f"  [{hint:>12}] {r.get('situation_id','<none>')}  [{flag}]  {desc[:40]}")

    passed = sum(1 for r in results if r.get("pass"))
    print(f"\n=== H6: custom situation generation ===")
    print(f"  {passed}/{len(results)} succeeded")
    print(f"  H6 RESULT: {'PASS' if passed == len(results) else 'FAIL'}")

    out = {
        "use_mocks": settings.use_mocks,
        "n_total": len(results),
        "n_passed": passed,
        "pass": passed == len(results),
        "results": results,
    }
    path = RESULTS_DIR / "eval_custom_situation.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved → {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true")
    p.parse_args()
    asyncio.run(main())
