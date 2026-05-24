"""v3: 규칙 기반 표준 코칭 카드 (LLM 사용 X).

자유 재작성(`rewrite.py`, H3)과 별개의 결정론적 추천기:
- 사용자에게 "왜 이 팁이 나왔는지" 정확히 설명할 수 있다.
- analysis row만 보고 즉시 계산되므로 GET /sessions/{id}/coaching 시점에 매번 호출 가능.

3가지 카드(§3.5):
  - lead_with_conclusion : 결론을 앞에 두라 — goal_alignment 약하고 평균 답변이 긴 경우
  - shorten_answer       : 답변을 줄여라     — too_long_turn_count >= 2
  - clear_ending         : 끝음을 명확히      — tail_clarity < 0.6
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class CoachingTip:
    id: str
    title: str
    body: str


Trigger = Callable[[Any], bool]


TIP_TEMPLATES: dict[str, dict] = {
    "lead_with_conclusion": {
        "title": "핵심부터 말해보세요",
        "trigger": (
            lambda a: a.flow_goal_alignment < 3.5  # type: ignore[union-attr]
            and a.answer_length_sec_mean > 25      # type: ignore[union-attr]
        ),
        "body": (
            "답변의 결론이 뒤쪽에 나오면 듣는 사람이 핵심을 놓치기 쉬워요. "
            "첫 문장에 결론을 먼저 두고 이유와 근거를 뒤에 붙여보세요."
        ),
    },
    "shorten_answer": {
        "title": "답변 길이를 줄여보세요",
        "trigger": lambda a: a.too_long_turn_count >= 2,  # type: ignore[union-attr]
        "body": (
            "한 답변이 길어질수록 전달력이 떨어집니다. "
            "핵심 1~2문장 + 짧은 근거 1개 정도로 정리해보세요."
        ),
    },
    "clear_ending": {
        "title": "문장 끝을 더 명확히 말해보세요",
        "trigger": lambda a: a.tail_clarity < 0.6,  # type: ignore[union-attr]
        "body": (
            "문장 끝에서 음량이 작아지거나 흐려지면 상대가 되묻기 쉬워요. "
            "마지막 음절까지 호흡을 유지해보세요."
        ),
    },
}


def generate_coaching_tips(analysis: Any) -> list[CoachingTip]:
    """규칙 기반으로 활성화된 팁 카드를 반환. 활성 팁이 없으면 빈 리스트.

    트리거에서 비교 대상이 None이면 TypeError가 발생할 수 있다 — 그 경우
    "데이터 부족"으로 간주해 해당 팁은 발화시키지 않는다(False).
    """
    out: list[CoachingTip] = []
    for tip_id, spec in TIP_TEMPLATES.items():
        try:
            fired = bool(spec["trigger"](analysis))
        except (TypeError, AttributeError):
            fired = False
        if fired:
            out.append(CoachingTip(id=tip_id, title=spec["title"], body=spec["body"]))
    return out
