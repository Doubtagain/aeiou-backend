"""LLM adapter (§4): Protocol + real Claude impl (filled in step 8) + a fully
deterministic Mock.

Contract for `chat_json(system, user, schema)`:
  * `user` embeds the task INPUT as a JSON block (extractable by both the real
    model, which just reads it, and MockLLM, which parses it).
  * `schema` is a {output_key: human description} dict. Its keys both instruct
    the real model and let MockLLM dispatch to the right deterministic handler.

This keeps mock and real on the exact same call surface.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Optional, Protocol, runtime_checkable

from ..config import settings
from ..constants import AVOID_MARKERS, FILLER_DICT, POLYSEMOUS, STRONG_FILLERS
from .types import Message


@runtime_checkable
class LLM(Protocol):
    async def chat(self, system: str, messages: list[Message]) -> str: ...

    async def chat_json(self, system: str, user: str, schema: dict) -> dict: ...


# --------------------------------------------------------------------------- #
# Shared helpers (used by both real and mock impls)
# --------------------------------------------------------------------------- #
def extract_json_block(text: str) -> Optional[Any]:
    """Return the first balanced top-level JSON value in `text`, or None.

    Quote/escape aware so braces inside strings don't fool the depth counter.
    """
    if not text:
        return None
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None


def schema_instruction(schema: dict) -> str:
    lines = ["다음 키를 가진 JSON 객체 하나만 출력하세요. 설명 문장이나 코드펜스(```)는 쓰지 마세요."]
    for key, desc in schema.items():
        lines.append(f'- "{key}": {desc}')
    return "\n".join(lines)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _tokenize_ko(text: str) -> list[str]:
    return _TOKEN_RE.findall(text or "")


def _is_content_word(token: Optional[str]) -> bool:
    """A meaningful Hangul word (so a polysemous candidate before it is NOT a filler)."""
    if not token:
        return False
    core = "".join(_TOKEN_RE.findall(token))
    if not core:
        return False
    if core in FILLER_DICT:
        return False
    return any("가" <= c <= "힣" for c in core)


def _quality_base(transcript: str) -> float:
    """Crude 1-5 quality proxy from filler density + avoidance markers.

    Lets the mock produce directionally-correct scores (good > bad) WITHOUT a
    real model, so demo_run --mock and the pipeline test are meaningful.
    """
    toks = _tokenize_ko(transcript)
    n = max(len(toks), 1)
    filler_density = sum(1 for t in toks if t in FILLER_DICT) / n
    avoid = sum(transcript.count(m) for m in AVOID_MARKERS)
    base = 4.3 - 9.0 * filler_density - 0.25 * avoid
    return _clamp(base, 1.0, 5.0)


def _dim_score(dim: str, base: float) -> float:
    off = (int(hashlib.md5(dim.encode("utf-8")).hexdigest(), 16) % 7 - 3) / 10.0
    score = base + off
    if "avoid" in dim or "회피" in dim:
        score -= 0.3
    return round(_clamp(score, 1.0, 5.0), 2)


# --------------------------------------------------------------------------- #
# Real adapter — implemented in step 8 (lazy SDK import so this module imports
# without the `anthropic` package installed).
# --------------------------------------------------------------------------- #
class ClaudeLLM:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or settings.anthropic_model
        self._client = None  # created lazily in step 8

    async def chat(self, system: str, messages: list[Message]) -> str:  # pragma: no cover
        raise NotImplementedError("ClaudeLLM.chat is implemented in step 8")

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:  # pragma: no cover
        raise NotImplementedError("ClaudeLLM.chat_json is implemented in step 8")


# --------------------------------------------------------------------------- #
# Deterministic mock
# --------------------------------------------------------------------------- #
_MOCK_AI_LINES = [
    "음… 그래서 네 진짜 마음은 어떤 건데?",
    "그렇게 말하니까 좀 서운하긴 한데, 더 얘기해 봐.",
    "그건 좀 핑계처럼 들리는데. 솔직하게 말해 줄래?",
    "알겠어. 그러면 앞으로는 어떻게 하고 싶은데?",
    "…그 말 들으니까 마음이 좀 복잡하다.",
]


class MockLLM:
    """Deterministic. Dispatches on `schema` keys, reads input JSON from `user`."""

    async def chat(self, system: str, messages: list[Message]) -> str:
        idx = len(messages) % len(_MOCK_AI_LINES)
        return _MOCK_AI_LINES[idx]

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        keys = set(schema or {})
        data = extract_json_block(user)
        if "classifications" in keys:
            return self._fillers(data)
        if "rewrites" in keys:
            return self._rewrites(data)
        if "better_side" in keys:
            return self._compare(data)
        if "scores" in keys:
            return self._judge(data)
        return {k: None for k in keys}

    # -- filler classification --
    def _fillers(self, data: Any) -> dict:
        candidates = (data or {}).get("candidates", []) if isinstance(data, dict) else []
        out = []
        for c in candidates:
            word = (c.get("word") or "").strip()
            after = c.get("after") or []
            nxt = after[0] if after else None
            if word in STRONG_FILLERS:
                is_filler = True
            elif word in POLYSEMOUS:
                # demonstrative/adverb modifying a real word → meaningful, not a filler
                is_filler = not _is_content_word(nxt)
            else:
                is_filler = word in FILLER_DICT
            out.append({"index": int(c.get("index", len(out))), "is_filler": bool(is_filler)})
        return {"classifications": out}

    # -- LLM-as-judge --
    def _judge(self, data: Any) -> dict:
        data = data or {}
        transcript = data.get("transcript", "") if isinstance(data, dict) else ""
        dims = data.get("dimensions", []) if isinstance(data, dict) else []
        base = _quality_base(transcript)
        scores = {d: _dim_score(d, base) for d in dims}
        return {"scores": scores, "comment": "(mock) 휴리스틱 기반 결정론적 평가"}

    # -- improvement rewrites --
    def _rewrites(self, data: Any) -> dict:
        data = data or {}
        goal_label = data.get("goal_label") or data.get("goal") or "목표"
        turns = data.get("turns", []) if isinstance(data, dict) else []
        rewrites = []
        for t in turns:
            text = t.get("text", "")
            clean = " ".join(w for w in _tokenize_ko(text) if w not in FILLER_DICT)
            v1 = f"{clean}".strip() or text
            v2 = f"솔직히 말하면, {clean}".strip()
            rewrites.append(
                {
                    "source_turn_id": t.get("turn_id"),
                    "original_text": text,
                    "variants": [
                        {"text": v1, "rationale": f"불필요한 군말을 빼 '{goal_label}'에 더 또렷하게 맞춤."},
                        {"text": v2, "rationale": "감정을 먼저 드러내 진솔함을 강화."},
                    ],
                }
            )
        return {"rewrites": rewrites}

    # -- retake comparison --
    def _compare(self, data: Any) -> dict:
        data = data or {}
        base = (data.get("baseline") or {}) if isinstance(data, dict) else {}
        ret = (data.get("retake") or {}) if isinstance(data, dict) else {}

        def overall(side: dict) -> float:
            if "judge_overall" in side and side["judge_overall"] is not None:
                return float(side["judge_overall"])
            # fall back to lower-filler-is-better
            return -float(side.get("filler_count", 0))

        b, r = overall(base), overall(ret)
        if r > b + 1e-6:
            better, verdict = "retake", "리테이크 세션이 표현 흐름과 전달력에서 뚜렷한 개선을 보였습니다."
        elif b > r + 1e-6:
            better, verdict = "baseline", "베이스라인 세션이 더 나았고 리테이크에서 개선이 확인되지 않았습니다."
        else:
            better, verdict = "tie", "두 세션의 차이가 뚜렷하지 않습니다."
        return {
            "better_side": better,
            "verdict": verdict,
            "diff_summary": data.get("quant_diff", {}),
        }


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_llm() -> "LLM":
    if settings.use_mocks or not settings.anthropic_api_key:
        return MockLLM()
    return ClaudeLLM(settings.anthropic_api_key, settings.anthropic_model)
