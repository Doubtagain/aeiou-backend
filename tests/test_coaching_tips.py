"""v3 표준 코칭 카드 — 규칙 기반 트리거(결정론)."""
from types import SimpleNamespace

from app.analysis.coaching_tips import generate_coaching_tips


def _analysis(**overrides):
    base = dict(
        flow_goal_alignment=4.5,
        answer_length_sec_mean=10.0,
        too_long_turn_count=0,
        tail_clarity=0.9,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_no_tips_when_strong_analysis():
    assert generate_coaching_tips(_analysis()) == []


def test_shorten_answer_triggers_on_too_long_turns():
    tips = generate_coaching_tips(_analysis(too_long_turn_count=3))
    assert any(t.id == "shorten_answer" for t in tips)


def test_clear_ending_triggers_on_low_tail_clarity():
    tips = generate_coaching_tips(_analysis(tail_clarity=0.3))
    assert any(t.id == "clear_ending" for t in tips)


def test_lead_with_conclusion_requires_both_conditions():
    # 둘 중 하나만 만족하면 발화하지 않는다 (AND 조건)
    only_goal = generate_coaching_tips(_analysis(flow_goal_alignment=2.0))
    assert all(t.id != "lead_with_conclusion" for t in only_goal)
    only_long = generate_coaching_tips(_analysis(answer_length_sec_mean=40.0))
    assert all(t.id != "lead_with_conclusion" for t in only_long)
    # 둘 다 만족하면 트리거
    both = generate_coaching_tips(
        _analysis(flow_goal_alignment=2.5, answer_length_sec_mean=40.0)
    )
    assert any(t.id == "lead_with_conclusion" for t in both)


def test_none_fields_do_not_crash():
    # 분석이 부분적으로 비어 있어도(필드 None) 예외 없이 빈 리스트/일부 결과를 반환.
    a = SimpleNamespace(
        flow_goal_alignment=None,
        answer_length_sec_mean=None,
        too_long_turn_count=None,
        tail_clarity=None,
    )
    # 모두 None이면 어떤 트리거도 발화하면 안 된다.
    assert generate_coaching_tips(a) == []


def test_all_three_tips_can_fire_together():
    tips = generate_coaching_tips(
        _analysis(
            flow_goal_alignment=2.0,
            answer_length_sec_mean=40.0,
            too_long_turn_count=4,
            tail_clarity=0.4,
        )
    )
    ids = {t.id for t in tips}
    assert ids == {"lead_with_conclusion", "shorten_answer", "clear_ending"}
