"""반복 표현 검출(v3) — 사용자 고유 n-gram 빈도 기반."""
from app.analysis.repetition import detect_repetitions


def test_detects_phrase_repeated_three_times():
    # "그런 거 있잖아요"가 3개의 다른 턴에서 정확히 1번씩 등장 (총 3회)
    transcripts = [
        "근데 그런 거 있잖아요 사실은 좀 그래요",
        "그런 거 있잖아요 정말로 어려운 부분이에요",
        "결국에는 그런 거 있잖아요 어쩔 수 없는 거죠",
    ]
    res = detect_repetitions(transcripts, min_freq=3)
    phrases = [p["phrase"] for p in res["repeated_phrases"]]
    # 3-어절 반복이 잡혀야 한다
    assert "그런 거 있잖아요" in phrases
    hit = next(p for p in res["repeated_phrases"] if p["phrase"] == "그런 거 있잖아요")
    assert hit["count"] == 3
    assert hit["turns"] == [0, 1, 2]
    # 더 짧은 prefix "그런 거"는 같은 빈도로는 중복 노이즈로 잡혀선 안 됨
    assert "그런 거" not in phrases
    assert 0 < res["repetition_ratio"] <= 1.0


def test_no_repetition_returns_empty():
    transcripts = [
        "오늘은 비가 와서 우산을 챙겼습니다",
        "내일은 맑을 거라고 들었어요",
        "주말에는 산책을 하려고 합니다",
    ]
    res = detect_repetitions(transcripts, min_freq=3)
    assert res["repeated_phrases"] == []
    assert res["repetition_ratio"] == 0.0


def test_filler_only_ngrams_excluded():
    # 필러만으로 구성된 n-gram("음 어")은 제외돼야 한다 — 반복어 metric은 필러와 분리.
    transcripts = ["음 어 음 어 음 어", "음 어 그래서요", "음 어 그래서 말이죠"]
    res = detect_repetitions(transcripts, min_freq=2)
    assert all("음 어" != p["phrase"] for p in res["repeated_phrases"])


def test_min_freq_threshold():
    # 2회만 등장하면 디폴트(min_freq=3)로는 검출되지 않아야 한다.
    transcripts = ["진짜 좋은 점은 명확합니다", "진짜 좋은 점은 분명히 있어요"]
    assert detect_repetitions(transcripts, min_freq=3)["repeated_phrases"] == []
    # min_freq=2로 낮추면 잡힌다.
    res2 = detect_repetitions(transcripts, min_freq=2)
    assert any(p["phrase"].startswith("진짜 좋은") for p in res2["repeated_phrases"])


def test_empty_transcripts():
    assert detect_repetitions([])["repeated_phrases"] == []
    assert detect_repetitions(["", "   "])["total_tokens"] == 0
