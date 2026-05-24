"""Korean filler detection (§5.3): dictionary candidates → LLM context check.

Stage 1 (`candidate_fillers`) is cheap and deterministic; it only proposes.
Polysemous words ("그"/"좀"/"막" …) are proposed as candidates ONLY — whether
they are real fillers is decided in stage 2 (`classify_fillers`) by the LLM, which
sees a ±5-word context window and judges the whole batch in one call.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from ..constants import FILLER_DICT, POLYSEMOUS  # noqa: F401 (FILLER_DICT re-exported per spec)

if TYPE_CHECKING:
    from ..conversation.llm import LLM
    from ..conversation.types import Word

_CONTEXT = 5
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


@dataclass
class FillerCandidate:
    index: int  # position in the token sequence
    word: str
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    is_polysemous: bool = False
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None


@dataclass
class Filler:
    index: int
    word: str
    is_filler: bool
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None


def _normalize(token: str) -> str:
    found = _TOKEN_RE.findall(token or "")
    return "".join(found)


def candidate_fillers(
    transcript_verbatim: str, words: Optional[list["Word"]] = None
) -> list[FillerCandidate]:
    """Stage 1: dictionary match. Returns one candidate per matched token."""
    if words:
        tokens = [_normalize(w.text) for w in words]
        spans = [(getattr(w, "start_ms", None), getattr(w, "end_ms", None)) for w in words]
    else:
        tokens = _TOKEN_RE.findall(transcript_verbatim or "")
        spans = [(None, None)] * len(tokens)

    candidates: list[FillerCandidate] = []
    for i, tok in enumerate(tokens):
        if tok and tok in FILLER_DICT:
            candidates.append(
                FillerCandidate(
                    index=i,
                    word=tok,
                    before=[t for t in tokens[max(0, i - _CONTEXT) : i] if t],
                    after=[t for t in tokens[i + 1 : i + 1 + _CONTEXT] if t],
                    is_polysemous=tok in POLYSEMOUS,
                    start_ms=spans[i][0],
                    end_ms=spans[i][1],
                )
            )
    return candidates


_JUDGE_SYSTEM = (
    "당신은 한국어 발화에서 군말(필러)을 판정하는 전문가다. "
    "필러란 의미 없이 채워 넣는 말(예: 음, 어, 그냥, 있잖아)이나, "
    "다의어가 머뭇거림으로 쓰인 경우를 뜻한다. "
    "'그 사람', '좀 더'처럼 뒤 단어를 실제로 수식하면 필러가 아니다. "
    "각 후보를 문맥에 근거해 엄격히 판정하라."
)


async def classify_fillers(
    candidates: list[FillerCandidate], llm: "LLM"
) -> list[Filler]:
    """Stage 2: one batched LLM call classifies every candidate in context."""
    if not candidates:
        return []
    payload = {
        "candidates": [
            {"index": c.index, "word": c.word, "before": c.before, "after": c.after}
            for c in candidates
        ]
    }
    user = (
        "다음 후보들이 진짜 필러인지 각각 판정하라. before/after는 좌우 문맥 단어다.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    schema = {
        "classifications": "[{\"index\": int, \"is_filler\": bool}, ...] 형태의 배열 (모든 후보 포함)"
    }
    result = await llm.chat_json(_JUDGE_SYSTEM, user, schema)

    verdicts: dict[int, bool] = {}
    for item in (result or {}).get("classifications", []) or []:
        try:
            verdicts[int(item["index"])] = bool(item["is_filler"])
        except (KeyError, TypeError, ValueError):
            continue

    by_index = {c.index: c for c in candidates}
    fillers: list[Filler] = []
    for idx, cand in by_index.items():
        # default: trust the dictionary for unambiguous words if the LLM omitted one
        is_filler = verdicts.get(idx, not cand.is_polysemous)
        fillers.append(
            Filler(index=idx, word=cand.word, is_filler=is_filler,
                   start_ms=cand.start_ms, end_ms=cand.end_ms)
        )
    fillers.sort(key=lambda f: f.index)
    return fillers


def confirmed_fillers(fillers: list[Filler]) -> list[Filler]:
    return [f for f in fillers if f.is_filler]


async def analyze_fillers(
    transcript_verbatim: str, words: Optional[list["Word"]], llm: "LLM"
) -> dict[str, Any]:
    """Convenience: candidates → classify → count + density (per-token)."""
    n_tokens = len(words) if words else len(_TOKEN_RE.findall(transcript_verbatim or ""))
    candidates = candidate_fillers(transcript_verbatim, words)
    fillers = await classify_fillers(candidates, llm)
    confirmed = confirmed_fillers(fillers)
    count = len(confirmed)
    density = round(count / n_tokens, 4) if n_tokens else 0.0
    return {
        "count": count,
        "density": density,
        "n_tokens": n_tokens,
        "fillers": [f.__dict__ for f in fillers],
    }
