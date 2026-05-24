"""Filler detection: dictionary matching + polysemy disambiguation (§8)."""
import asyncio

from app.analysis.fillers import (
    FILLER_DICT,
    analyze_fillers,
    candidate_fillers,
    classify_fillers,
)
from app.conversation.llm import MockLLM
from app.conversation.types import Word


def test_dictionary_candidates_found():
    text = "음 어 그냥 있잖아 정말 좋았어"
    words = {c.word for c in candidate_fillers(text)}
    assert {"음", "어", "그냥", "있잖아"} <= words
    # content words are never candidates
    assert "정말" not in words
    assert "좋았어" not in words


def test_polysemous_demonstrative_is_not_a_filler():
    # "그" modifies the noun "사람이" → meaningful; standalone "어" → filler.
    text = "어 그 사람이 정말 좋았어"
    cands = candidate_fillers(text)
    assert {c.word for c in cands} == {"어", "그"}

    fillers = asyncio.run(classify_fillers(cands, MockLLM()))
    eo = next(f for f in fillers if f.word == "어")
    geu = next(f for f in fillers if f.word == "그")
    assert eo.is_filler is True
    assert geu.is_filler is False  # the whole point: 의미로 쓰인 "그"는 필러 아님


def test_repeated_polysemous_is_a_filler():
    # "그 그" — the first "그" is followed by another filler, not a content word.
    text = "그 그 사람이 좋았어"
    fillers = asyncio.run(classify_fillers(candidate_fillers(text), MockLLM()))
    first_geu = min((f for f in fillers if f.word == "그"), key=lambda f: f.index)
    assert first_geu.is_filler is True


def test_analyze_fillers_count_and_density_with_word_timestamps():
    words = [
        Word("어", 0, 200),
        Word("그", 200, 400),
        Word("사람이", 400, 800),
        Word("좋았어", 800, 1200),
    ]
    res = asyncio.run(analyze_fillers("어 그 사람이 좋았어", words, MockLLM()))
    assert res["n_tokens"] == 4
    assert res["count"] == 1  # only "어" survives classification
    assert 0.0 < res["density"] <= 1.0
    # every confirmed filler is a known dictionary word
    confirmed = [f for f in res["fillers"] if f["is_filler"]]
    assert [f["word"] for f in confirmed] == ["어"]
    assert all(f["word"] in FILLER_DICT for f in confirmed)
