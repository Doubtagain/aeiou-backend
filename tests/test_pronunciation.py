"""v3 발음 분석 — LLM 추정 기반 weak_words (PoC, mock 결정론)."""
import asyncio
from types import SimpleNamespace

from app.analysis.pronunciation import analyze_pronunciation
from app.conversation.llm import MockLLM


def _user_turn(idx, text, start_ms=0, end_ms=2000):
    return SimpleNamespace(
        speaker="user",
        turn_index=idx,
        transcript=text,
        transcript_verbatim=text,
        start_ts_ms=start_ms,
        end_ts_ms=end_ms,
    )


def test_returns_weak_words_for_user_turns():
    turns = [
        _user_turn(1, "정확하게 발음하기는 정말 쉽지 않습니다", 0, 5000),
        _user_turn(3, "그래도 분명하게 말씀드리겠습니다", 6000, 11000),
    ]
    res = asyncio.run(analyze_pronunciation(turns, MockLLM()))
    assert "weak_words" in res
    assert len(res["weak_words"]) <= 3
    assert len(res["weak_words"]) >= 1
    for w in res["weak_words"]:
        assert w["word"]
        assert w["articulation_tip"]
        assert isinstance(w["turn_index"], int)


def test_empty_when_no_user_turns():
    turns = [
        SimpleNamespace(speaker="ai", turn_index=0, transcript="안녕하세요", transcript_verbatim=None),
    ]
    res = asyncio.run(analyze_pronunciation(turns, MockLLM()))
    assert res == {"weak_words": []}


def test_dedup_same_word_same_turn():
    # 같은 (turn_index, word) 조합은 중복 제거된다.
    turns = [_user_turn(2, "발표 발표 발표 잘하기 잘하기 잘하기", 0, 6000)]
    res = asyncio.run(analyze_pronunciation(turns, MockLLM()))
    seen = set()
    for w in res["weak_words"]:
        key = (w["turn_index"], w["word"])
        assert key not in seen
        seen.add(key)
