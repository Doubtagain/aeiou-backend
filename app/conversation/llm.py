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
    """Return the first *parseable* balanced JSON value in `text`, or None.

    Tries every '{'/'[' opener in turn so stray brackets in surrounding prose
    (e.g. a label like "[입력]") don't defeat extraction. Quote/escape aware.
    """
    if not text:
        return None
    for start in range(len(text)):
        opener = text[start]
        if opener not in "{[":
            continue
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
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break  # malformed → try the next opener
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
# Real adapter — claude-sonnet-4-6 via the Anthropic SDK (lazy import so this
# module loads without the `anthropic` package installed).
# --------------------------------------------------------------------------- #
def _text_from(msg: Any) -> str:
    parts = []
    for block in getattr(msg, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


class ClaudeLLM:
    # NOTE (H1): chat_json uses temperature 0.4 (NOT 0) so judge variance is
    # measurable. Conversation chat uses 0.7 for natural replies.
    def __init__(self, api_key: str, model: str | None = None) -> None:
        from anthropic import AsyncAnthropic

        self.model = model or settings.anthropic_model
        self.client = AsyncAnthropic(api_key=api_key)

    async def chat(self, system: str, messages: list[Message]) -> str:
        msg = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0.7,
            system=system,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return _text_from(msg)

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        sys = system + " 반드시 유효한 JSON 객체 하나만 출력한다."
        prompt = user + "\n\n" + schema_instruction(schema)
        for attempt in range(2):
            msg = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0.4,
                system=sys,
                messages=[{"role": "user", "content": prompt}],
            )
            data = extract_json_block(_text_from(msg))
            if isinstance(data, dict):
                return data
            prompt = (
                user
                + "\n\n"
                + schema_instruction(schema)
                + "\n직전 응답이 JSON이 아니었다. 코드펜스 없이 JSON 객체만 출력하라."
            )
        return {}


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

# Canned dialogues for synth_data --mock (user-first, alternating). Generic but
# plausible; the situation-specific opening line is prepended by synth_data.
_MOCK_DIALOGUE_GOOD = [
    ("user", "응, 오늘은 너한테 꼭 분명하게 말하고 싶었어."),
    ("ai", "그래, 듣고 있어. 편하게 말해 줘."),
    ("user", "우리 관계를 여기서 깔끔하게 정리하는 게 서로에게 맞다고 생각해."),
    ("ai", "그렇게 결론 내린 이유를 들어도 될까?"),
    ("user", "함께한 시간은 정말 소중했지만, 지금은 각자의 길을 가는 게 맞아."),
    ("ai", "마음은 아프지만 네 진심은 잘 알겠어."),
    ("user", "그동안 고마웠고, 너도 나도 더 좋은 사람으로 지내길 바라."),
    ("ai", "고마워. 네 말 덕분에 나도 마음을 정리할 수 있을 것 같아."),
]
_MOCK_DIALOGUE_BAD = [
    ("user", "음… 그 뭐랄까, 그냥 좀 어… 그게 말이야."),
    ("ai", "천천히 말해도 돼. 무슨 얘기야?"),
    ("user", "어… 그냥 막 그게, 딱히 뭐 그런 건 아닌데 어쨌든 좀 그래."),
    ("ai", "그게 다야? 진심이 잘 안 느껴져."),
    ("user", "글쎄… 잘 모르겠어. 그냥 뭐 어떻게 해야 할지 음 모르겠어."),
    ("ai", "네가 원하는 게 뭔지 말해 줄 수 있어?"),
    ("user", "막 그냥 어… 나중에 얘기하면 안 될까? 지금은 좀 그래."),
    ("ai", "자꾸 피하는 것 같아서 속상해."),
]


class MockLLM:
    """Deterministic. Dispatches on `schema` keys, reads input JSON from `user`."""

    async def chat(self, system: str, messages: list[Message]) -> str:
        idx = len(messages) % len(_MOCK_AI_LINES)
        return _MOCK_AI_LINES[idx]

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        keys = set(schema or {})
        data = extract_json_block(user)
        if "dialogue" in keys:
            return self._dialogue(data)
        if "classifications" in keys:
            return self._fillers(data)
        if "rewrites" in keys:
            return self._rewrites(data)
        if "better_side" in keys:
            return self._compare(data)
        if "scores" in keys:
            return self._judge(data)
        if "weak_words" in keys:
            return self._weak_words(data)
        if "situation" in keys:
            return self._situation(data)
        return {k: None for k in keys}

    # -- dialogue script generation (synth_data) --
    def _dialogue(self, data: Any) -> dict:
        quality = (data or {}).get("quality", "good") if isinstance(data, dict) else "good"
        if quality == "bad":
            turns = _MOCK_DIALOGUE_BAD
        elif quality == "mixed":
            # alternate good/bad user turns
            turns = []
            for i, (g, b) in enumerate(zip(_MOCK_DIALOGUE_GOOD, _MOCK_DIALOGUE_BAD)):
                turns.append(b if (g[0] == "user" and i % 2 == 0) else g)
        else:
            turns = _MOCK_DIALOGUE_GOOD
        return {"dialogue": [{"speaker": s, "text": t} for s, t in turns]}

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

    # -- v3 custom situation generation (Step 7) --
    def _situation(self, data: Any) -> dict:
        data = data or {}
        desc = (data.get("description") or "").strip() if isinstance(data, dict) else ""
        hint = (data.get("category_hint") or "emotional") if isinstance(data, dict) else "emotional"
        hint = hint if hint in {"emotional", "interview", "presentation", "business"} else "emotional"
        # 타이틀: 설명 첫 30자
        title = (desc[:30] + "…") if len(desc) > 30 else (desc or "사용자 맞춤 상황")
        # ID: hash로 결정론
        digest = hashlib.md5(desc.encode("utf-8")).hexdigest()[:8]
        sid = f"user_{hint}_{digest}"
        return {
            "situation": {
                "id": sid,
                "title": title,
                "category": hint,
                "difficulty": 2,
                "ai_persona": (
                    "당신은 사용자가 묘사한 상황의 상대 역할이다. "
                    "매 턴 1~3문장으로 한국어 구어체로 자연스럽게 반응한다. "
                    "코치가 되지 말고 끝까지 인물에 머문다. "
                    "사용자가 모호하게 말하면 한 번 더 짚어 묻는다. "
                    "현실적인 톤으로, 과장된 신파나 폭언은 피한다. "
                    "필요할 때만 후속 질문으로 유도하고, 답을 대신 주지 않는다."
                ),
                "opening_line": "안녕하세요. 편하게 말씀해 주세요. 어떤 점부터 이야기해보고 싶으세요?",
                "duration_target_sec": [120, 240],
                "answer_length_guideline_sec": (
                    60 if hint == "interview" else 90 if hint == "presentation" else 30
                ),
                "goal_options": [
                    {
                        "id": "primary_goal",
                        "label": "핵심 메시지를 분명히 전달하기",
                        "eval_focus": ["핵심우선", "결론먼저", "명확성"],
                    },
                    {
                        "id": "audience_aware",
                        "label": "상대 입장을 고려해 말하기",
                        "eval_focus": ["공감표현", "상호존중", "맞춤형설명"],
                    },
                ],
                "target_phonemes": [],
            }
        }

    # -- v3 pronunciation: heuristic mock weak-word picker --
    def _weak_words(self, data: Any) -> dict:
        turns = (data or {}).get("turns", []) if isinstance(data, dict) else []
        # 초성 자모 추출용 (한글 음절 → 초성 19개)
        _INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"

        def first_initial(word: str) -> str:
            if not word:
                return ""
            ch = word[0]
            if "가" <= ch <= "힣":
                return _INITIALS[(ord(ch) - 0xAC00) // (21 * 28)]
            return ch

        out: list[dict] = []
        for t in turns:
            text = (t.get("text") if isinstance(t, dict) else "") or ""
            toks = [w for w in _tokenize_ko(text) if len(w) >= 2]
            if not toks:
                continue
            longest = max(toks, key=len)
            initial = first_initial(longest) or longest[0]
            out.append(
                {
                    "turn_index": int(t.get("turn_index", 0)) if isinstance(t, dict) else 0,
                    "word": longest,
                    "phoneme_focus": initial,
                    "articulation_tip": (
                        f"'{initial}' 음을 첫 음절에서 또렷이 짚고, 끝 음절까지 호흡을 유지해 발음해보세요."
                    ),
                }
            )
            if len(out) >= 3:
                break
        return {"weak_words": out}

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
