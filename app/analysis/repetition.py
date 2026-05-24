"""v3: 반복 표현(사용자 고유) 검출. 필러(`fillers.py`)와는 분리된 모듈.

필러는 단일 토큰/관용표현("음", "어", "있잖아") 사전 매칭.
반복어는 **사용자 자신의 표현**이 한 세션 안에서 자주 등장하는 케이스
(예: "그런 거 있잖아요", "그러니까 결국에는") — 사전 없이 n-gram 빈도로 잡는다.

토큰 단위는 한국어 **어절**(공백 분리). 형태소 분석은 사용하지 않는다 — 반복은 표면형이 본질.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

from ..constants import FILLER_DICT

_MIN_N = 2
_MAX_N = 5
_MIN_FREQ_DEFAULT = 3

# 어절 가장자리 구두점만 제거 (내부 문자는 그대로). 한·영·숫자는 살림.
_TRIM_PUNCT = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """공백 분리 후 양끝 구두점만 다듬은 어절 리스트."""
    if not text:
        return []
    out: list[str] = []
    for raw in text.split():
        clean = _TRIM_PUNCT.sub("", raw)
        if clean:
            out.append(clean)
    return out


def _is_all_filler(ngram: tuple[str, ...]) -> bool:
    return all(tok in FILLER_DICT for tok in ngram)


def detect_repetitions(
    transcripts: Iterable[str],
    *,
    min_freq: int = _MIN_FREQ_DEFAULT,
    min_n: int = _MIN_N,
    max_n: int = _MAX_N,
) -> dict:
    """동일 세션 내 `min_freq`회 이상 등장한 n-gram(min_n..max_n 어절) 검출.

    Returns:
        repeated_phrases: [{"phrase": "...", "count": int, "turns": [i, ...]}], 빈도 내림차순
        repetition_ratio: 반복 n-gram이 차지하는 토큰 위치 비율 (0~1, 중복 카운트 없음)
        total_tokens: 사용된 전체 어절 수
    """
    per_turn = [_tokenize(t) for t in transcripts]
    total = sum(len(toks) for toks in per_turn)
    if total == 0:
        return {"repeated_phrases": [], "repetition_ratio": 0.0, "total_tokens": 0}

    counts: Counter[tuple[str, ...]] = Counter()
    turns_by: defaultdict[tuple[str, ...], set[int]] = defaultdict(set)
    positions_by: defaultdict[tuple[str, ...], list[tuple[int, int, int]]] = defaultdict(list)

    for ti, toks in enumerate(per_turn):
        for n in range(min_n, max_n + 1):
            if n > len(toks):
                break
            for i in range(0, len(toks) - n + 1):
                ngram = tuple(toks[i : i + n])
                if _is_all_filler(ngram):
                    continue
                counts[ngram] += 1
                turns_by[ngram].add(ti)
                positions_by[ngram].append((ti, i, n))

    detected = {ng: c for ng, c in counts.items() if c >= min_freq}
    if not detected:
        return {"repeated_phrases": [], "repetition_ratio": 0.0, "total_tokens": total}

    # 같은 빈도로 더 짧은 n-gram이 더 긴 n-gram에 포함되어 있으면(prefix/infix/suffix) 짧은 쪽 제거.
    # 예: "그런 거 있잖아요"가 3회 등장하면 "그런 거"도 3회로 잡히는데 후자는 노이즈.
    ngrams_sorted = sorted(detected.keys(), key=len, reverse=True)
    redundant: set[tuple[str, ...]] = set()
    for shorter in ngrams_sorted:
        if shorter in redundant:
            continue
        for longer in ngrams_sorted:
            if len(longer) <= len(shorter) or longer == shorter:
                continue
            if detected[longer] != detected[shorter]:
                continue
            # shorter가 longer에 연속 부분으로 포함?
            for k in range(0, len(longer) - len(shorter) + 1):
                if tuple(longer[k : k + len(shorter)]) == shorter:
                    redundant.add(shorter)
                    break

    # repetition_ratio: 검출 n-gram이 점유한 토큰 위치 집합(중복 없음) / 전체 토큰 수
    covered: set[tuple[int, int]] = set()
    for ng in detected:
        if ng in redundant:
            continue
        for ti, i, n in positions_by[ng]:
            for k in range(n):
                covered.add((ti, i + k))

    repeated = [
        {
            "phrase": " ".join(ng),
            "count": detected[ng],
            "turns": sorted(turns_by[ng]),
        }
        for ng in detected
        if ng not in redundant
    ]
    repeated.sort(key=lambda r: (-r["count"], -len(r["phrase"].split()), r["phrase"]))

    return {
        "repeated_phrases": repeated,
        "repetition_ratio": round(len(covered) / total, 4),
        "total_tokens": total,
    }
