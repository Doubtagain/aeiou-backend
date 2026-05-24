"""Signal metrics on synthetic audio: SPM, F0, silence, tail, latency (§8)."""
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from app.analysis import signal_metrics as sm

SR = 16000


def _sine_wav(path, freq=150.0, dur=1.0, amp=0.5, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    sf.write(str(path), (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _user_turn(text, start_ms, end_ms, audio_path=None):
    return SimpleNamespace(
        speaker="user",
        turn_index=0,
        transcript=text,
        transcript_verbatim=text,
        start_ts_ms=start_ms,
        end_ts_ms=end_ms,
        audio_path=audio_path,
    )


def test_spm_reasonable_range():
    # "안녕하세요 반갑습니다" = 10 Hangul syllables in 2.0 s → 300 SPM
    turns = [
        _user_turn("안녕하세요 반갑습니다", 0, 2000),
        _user_turn("정말 오랜만에 보네요", 3000, 5500),  # 9 syllables / 2.5 s ≈ 216 SPM
    ]
    mean, stdev = sm.compute_spm(turns)
    assert 200.0 <= mean <= 500.0  # H2 target band
    assert stdev > 0.0


def test_f0_matches_sine_frequency(tmp_path):
    wav = tmp_path / "sine150.wav"
    _sine_wav(wav, freq=150.0)
    stats = sm.compute_f0_stats(wav)
    assert stats["n_voiced"] > 0
    assert 135.0 <= stats["mean"] <= 165.0  # within ~10% of 150 Hz
    assert 80.0 <= stats["mean"] <= 300.0  # H2 target band


def test_silence_ratio_half_and_full(tmp_path):
    sr = SR
    tone = 0.5 * np.sin(2 * np.pi * 150 * np.arange(sr) / sr)  # 1 s tone
    sig = np.concatenate([tone, np.zeros(sr)]).astype("float32")  # +1 s silence
    half = tmp_path / "half.wav"
    sf.write(str(half), sig, sr)
    ratio = sm.compute_silence_ratio(half)
    assert 0.3 <= ratio <= 0.7  # roughly half silent

    silent = tmp_path / "silent.wav"
    sf.write(str(silent), np.zeros(sr, dtype="float32"), sr)
    assert sm.compute_silence_ratio(silent) == 1.0


def test_tail_clarity_constant_vs_decay(tmp_path):
    sr = SR
    t = np.arange(sr) / sr
    steady = tmp_path / "steady.wav"
    sf.write(str(steady), (0.5 * np.sin(2 * np.pi * 150 * t)).astype("float32"), sr)
    # constant-amplitude tone → tail energy ≈ overall energy
    assert sm.compute_tail_clarity(steady) >= 0.8

    decay = tmp_path / "decay.wav"
    env = np.linspace(1.0, 0.05, sr)  # fades out → trailing energy drops
    sf.write(str(decay), (env * 0.5 * np.sin(2 * np.pi * 150 * t)).astype("float32"), sr)
    assert sm.compute_tail_clarity(decay) < sm.compute_tail_clarity(steady)


def test_response_latencies():
    turns = [
        SimpleNamespace(speaker="ai", turn_index=0, start_ts_ms=0, end_ts_ms=1000),
        SimpleNamespace(speaker="user", turn_index=1, start_ts_ms=1300, end_ts_ms=3000),
        SimpleNamespace(speaker="ai", turn_index=2, start_ts_ms=3000, end_ts_ms=4000),
        SimpleNamespace(speaker="user", turn_index=3, start_ts_ms=4500, end_ts_ms=6000),
    ]
    lat = sm.compute_response_latencies(turns)
    assert lat["n"] == 2
    assert 300.0 <= lat["p50_ms"] <= 500.0
    assert lat["p90_ms"] >= lat["p50_ms"]


def test_answer_lengths_per_turn_and_too_long():
    # 1번 턴: 2초, 2번 턴: 70초(임계 60s 초과), 3번 턴: 5초
    turns = [
        _user_turn("안녕하세요", 0, 2000),               # 5음절 / 1어절 / 2.0s
        _user_turn("저는 발표를 시작합니다", 3000, 73000),  # 10음절 / 3어절 / 70.0s
        _user_turn("끝", 80000, 85000),                  # 1음절 / 1어절 / 5.0s
    ]
    res = sm.compute_answer_lengths(turns, threshold_sec=60.0)
    assert [p["turn_index"] for p in res["per_turn"]] == [0, 0, 0]  # SimpleNamespace 디폴트
    assert [p["syllables"] for p in res["per_turn"]] == [5, 10, 1]
    assert [p["words"] for p in res["per_turn"]] == [1, 3, 1]
    assert [p["sec"] for p in res["per_turn"]] == [2.0, 70.0, 5.0]
    assert res["too_long_turns"] == [0]  # 70초 턴 하나만 초과
    assert res["sec_mean"] > 0 and res["syllable_mean"] > 0
    assert res["threshold_sec"] == 60.0


def test_answer_length_threshold_resolution():
    # 디폴트 카테고리값
    assert sm.resolve_answer_length_threshold_sec("interview") == 60.0
    assert sm.resolve_answer_length_threshold_sec("presentation") == 90.0
    assert sm.resolve_answer_length_threshold_sec("emotional") == 30.0
    # YAML 명시값이 카테고리 디폴트보다 우선
    assert sm.resolve_answer_length_threshold_sec("interview", 45) == 45.0
    # 카테고리 모르고 override도 없으면 None
    assert sm.resolve_answer_length_threshold_sec(None) is None
