"""Quantitative delivery metrics (§5.3): SPM, F0, silence, tail clarity, latency.

Design notes for the PoC environment (Windows / Python 3.13):
  * F0 default is a pure-numpy FFT autocorrelation estimator (deterministic, no
    heavy deps). `librosa.pyin` is available via method="pyin" if installed.
  * VAD is energy-based by default; webrtcvad is used automatically if present.
All functions tolerate silent / empty audio without raising (return 0.0).
"""
from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

_HANGUL_SYLLABLE = re.compile(r"[가-힣]")
_F0_MIN_HZ = 30.0
_F0_MAX_HZ = 400.0


# --------------------------------------------------------------------------- #
# audio io / turn helpers
# --------------------------------------------------------------------------- #
def _load_mono(audio_path: str | Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    y, sr = sf.read(str(audio_path), dtype="float64", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return np.ascontiguousarray(y, dtype=np.float64), int(sr)


def _user_turns(turns: Iterable[Any]) -> list[Any]:
    return [t for t in turns if getattr(t, "speaker", None) == "user"]


def _turn_text(turn: Any) -> str:
    return getattr(turn, "transcript_verbatim", None) or getattr(turn, "transcript", None) or ""


def _turn_duration_ms(turn: Any) -> Optional[float]:
    s, e = getattr(turn, "start_ts_ms", None), getattr(turn, "end_ts_ms", None)
    if s is not None and e is not None and e > s:
        return float(e - s)
    path = getattr(turn, "audio_path", None)
    if path and Path(path).exists():
        try:
            import soundfile as sf

            info = sf.info(str(path))
            return info.frames / info.samplerate * 1000.0
        except Exception:
            return None
    return None


def count_hangul_syllables(text: str) -> int:
    return len(_HANGUL_SYLLABLE.findall(text or ""))


# --------------------------------------------------------------------------- #
# SPM — syllables per minute
# --------------------------------------------------------------------------- #
def compute_spm(turns: list[Any]) -> tuple[float, float]:
    """Per-user-turn (Hangul syllables / minutes spoken); return (mean, stdev)."""
    rates: list[float] = []
    for t in _user_turns(turns):
        dur_ms = _turn_duration_ms(t)
        syll = count_hangul_syllables(_turn_text(t))
        if not dur_ms or dur_ms <= 0 or syll == 0:
            continue
        rates.append(syll / (dur_ms / 60000.0))
    if not rates:
        return 0.0, 0.0
    mean = statistics.fmean(rates)
    stdev = statistics.pstdev(rates) if len(rates) > 1 else 0.0
    return round(mean, 2), round(stdev, 2)


# --------------------------------------------------------------------------- #
# F0
# --------------------------------------------------------------------------- #
def _autocorr(frame: np.ndarray) -> np.ndarray:
    n = len(frame)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    spec = np.fft.rfft(frame, n=size)
    ac = np.fft.irfft(spec * np.conjugate(spec), n=size)[:n]
    return ac


def _voiced_f0_values(y: np.ndarray, sr: int) -> list[float]:
    if y.size == 0:
        return []
    frame_len = max(256, int(0.040 * sr))
    hop = max(128, int(0.020 * sr))
    global_rms = float(np.sqrt(np.mean(y**2))) if y.size else 0.0
    thresh = max(1e-4, 0.15 * global_rms)
    min_lag = max(1, int(sr / _F0_MAX_HZ))
    max_lag = int(sr / _F0_MIN_HZ)
    out: list[float] = []
    for start in range(0, max(0, len(y) - frame_len), hop):
        frame = y[start : start + frame_len]
        rms = float(np.sqrt(np.mean(frame**2)))
        if rms < thresh:
            continue
        frame = frame - frame.mean()
        ac = _autocorr(frame)
        if ac[0] <= 0:
            continue
        hi = min(max_lag, len(ac) - 1)
        if hi <= min_lag:
            continue
        seg = ac[min_lag : hi + 1]
        peak = int(np.argmax(seg)) + min_lag
        if ac[peak] < 0.3 * ac[0]:  # weak periodicity → unvoiced
            continue
        f0 = sr / peak
        if _F0_MIN_HZ <= f0 <= _F0_MAX_HZ:
            out.append(f0)
    return out


def _f0_pyin(y: np.ndarray, sr: int) -> list[float]:
    import librosa  # optional

    f0, voiced, _ = librosa.pyin(
        y.astype(np.float32), fmin=_F0_MIN_HZ, fmax=_F0_MAX_HZ, sr=sr
    )
    return [float(v) for v, ok in zip(f0, voiced) if ok and not np.isnan(v)]


def _f0_summary(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "n_voiced": 0}
    arr = np.asarray(values)
    return {
        "mean": round(float(arr.mean()), 2),
        "stdev": round(float(arr.std()), 2),
        "min": round(float(arr.min()), 2),
        "max": round(float(arr.max()), 2),
        "n_voiced": int(arr.size),
    }


def compute_f0_stats(audio_path: str | Path, method: str = "auto") -> dict:
    """F0 mean/stdev/range over voiced frames, clipped to 30-400 Hz."""
    y, sr = _load_mono(audio_path)
    if method == "pyin":
        values = _f0_pyin(y, sr)
    else:
        values = _voiced_f0_values(y, sr)
    return _f0_summary(values)


# --------------------------------------------------------------------------- #
# Silence ratio (VAD)
# --------------------------------------------------------------------------- #
class EnergyVad:
    """Pure-numpy energy gate. Frames below a relative RMS threshold are silence."""

    def __init__(self, frame_ms: int = 30, rel_thresh: float = 0.2) -> None:
        self.frame_ms = frame_ms
        self.rel_thresh = rel_thresh

    def silence_ratio(self, y: np.ndarray, sr: int) -> float:
        if y.size == 0:
            return 1.0
        flen = max(1, int(self.frame_ms / 1000.0 * sr))
        n_frames = max(1, len(y) // flen)
        rms = np.array(
            [
                np.sqrt(np.mean(y[i * flen : (i + 1) * flen] ** 2))
                for i in range(n_frames)
            ]
        )
        peak = float(rms.max()) if rms.size else 0.0
        if peak <= 1e-6:
            return 1.0
        thresh = self.rel_thresh * peak
        silent = int(np.sum(rms < thresh))
        return round(silent / n_frames, 4)


class WebrtcVad:
    """Optional webrtcvad backend (used only if the package is installed)."""

    def __init__(self, aggressiveness: int = 2) -> None:
        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)

    def silence_ratio(self, y: np.ndarray, sr: int) -> float:
        from scipy.signal import resample

        target_sr = 16000
        if sr != target_sr:
            y = resample(y, int(len(y) * target_sr / sr))
            sr = target_sr
        pcm = np.clip(y * 32768.0, -32768, 32767).astype(np.int16).tobytes()
        flen = int(0.03 * sr) * 2  # 30ms, 16-bit
        frames = [pcm[i : i + flen] for i in range(0, len(pcm) - flen + 1, flen)]
        if not frames:
            return 1.0
        speech = sum(1 for f in frames if self._vad.is_speech(f, sr))
        return round(1.0 - speech / len(frames), 4)


def get_vad(prefer_webrtc: bool = True) -> Any:
    if prefer_webrtc:
        try:
            return WebrtcVad()
        except Exception:
            pass
    return EnergyVad()


def compute_silence_ratio(audio_path: str | Path, vad: Any = None) -> float:
    y, sr = _load_mono(audio_path)
    if vad is None:
        vad = get_vad()
    return vad.silence_ratio(y, sr)


# --------------------------------------------------------------------------- #
# Tail clarity
# --------------------------------------------------------------------------- #
def _trim_silence(y: np.ndarray, sr: int, rel_thresh: float = 0.1) -> np.ndarray:
    if y.size == 0:
        return y
    flen = max(1, int(0.02 * sr))
    n = len(y) // flen
    if n == 0:
        return y
    rms = np.array([np.sqrt(np.mean(y[i * flen : (i + 1) * flen] ** 2)) for i in range(n)])
    peak = float(rms.max())
    if peak <= 1e-6:
        return np.array([])
    voiced = np.where(rms >= rel_thresh * peak)[0]
    if voiced.size == 0:
        return np.array([])
    return y[voiced[0] * flen : (voiced[-1] + 1) * flen]


def compute_tail_clarity(audio_path: str | Path, tail_ms: int = 300) -> float:
    """RMS of the last `tail_ms` of speech / RMS of the whole utterance.

    Lower ⇒ the speaker trails off (끝음이 흐려짐)."""
    y, sr = _load_mono(audio_path)
    speech = _trim_silence(y, sr)
    if speech.size == 0:
        return 0.0
    rms_all = float(np.sqrt(np.mean(speech**2)))
    if rms_all <= 1e-9:
        return 0.0
    tail_n = min(len(speech), max(1, int(tail_ms / 1000.0 * sr)))
    rms_tail = float(np.sqrt(np.mean(speech[-tail_n:] ** 2)))
    return round(rms_tail / rms_all, 4)


# --------------------------------------------------------------------------- #
# Response latency
# --------------------------------------------------------------------------- #
def compute_response_latencies(turns: list[Any]) -> dict:
    """p50/p90 of (user start − preceding AI end), in ms."""
    ordered = sorted(turns, key=lambda t: getattr(t, "turn_index", 0))
    lat: list[float] = []
    prev_ai_end: Optional[int] = None
    for t in ordered:
        spk = getattr(t, "speaker", None)
        if spk == "ai":
            prev_ai_end = getattr(t, "end_ts_ms", None)
        elif spk == "user":
            start = getattr(t, "start_ts_ms", None)
            if prev_ai_end is not None and start is not None and start >= prev_ai_end:
                lat.append(float(start - prev_ai_end))
    if not lat:
        return {"p50_ms": 0.0, "p90_ms": 0.0, "n": 0, "latencies_ms": []}
    arr = np.asarray(lat)
    return {
        "p50_ms": round(float(np.percentile(arr, 50)), 1),
        "p90_ms": round(float(np.percentile(arr, 90)), 1),
        "n": int(arr.size),
        "latencies_ms": [round(x, 1) for x in lat],
    }


# --------------------------------------------------------------------------- #
# Session-level aggregation over user turns
# --------------------------------------------------------------------------- #
def compute_session_delivery(turns: list[Any], f0_method: str = "auto") -> dict:
    """Aggregate SPM / F0 / silence / tail clarity across user-turn audio."""
    spm_mean, spm_stdev = compute_spm(turns)

    f0_values: list[float] = []
    silence_vals: list[float] = []
    tail_vals: list[float] = []
    vad = get_vad()
    for t in _user_turns(turns):
        path = getattr(t, "audio_path", None)
        if not path or not Path(path).exists():
            continue
        y, sr = _load_mono(path)
        f0_values.extend(_f0_pyin(y, sr) if f0_method == "pyin" else _voiced_f0_values(y, sr))
        silence_vals.append(vad.silence_ratio(y, sr))
        tail_vals.append(compute_tail_clarity(path))

    f0 = _f0_summary(f0_values)
    return {
        "spm_mean": spm_mean,
        "spm_stdev": spm_stdev,
        "f0_mean": f0["mean"],
        "f0_stdev": f0["stdev"],
        "f0_range": [f0["min"], f0["max"]],
        "silence_ratio": round(statistics.fmean(silence_vals), 4) if silence_vals else 0.0,
        "tail_clarity": round(statistics.fmean(tail_vals), 4) if tail_vals else 0.0,
        **compute_response_latencies(turns),
    }
