"""v3 차별 기능: 발음 분석 — 텍스트 가이드 only (애니메이션 X).

PoC 단계 구현 방향:
  1) 사용자 턴의 verbatim transcript와 (가능하면) 오디오 길이를 LLM에게 보여주고,
  2) "발음이 뭉개졌을 가능성이 가장 높은 단어 3개"와 각 단어의 초점 음소를 받는다.
  3) 음소별 조음점 가이드는 LLM이 함께 생성(예: 'ㅊ → 혀끝을 윗잇몸 근처에...').

실제 Azure PA 통합은 v3.1 범위. PoC에서는 LLM 추정 + 발화 시간 길이를 힌트로 사용.
응답 형식:
  {
    "weak_words": [
      {"word": "상처", "turn_index": 3, "phoneme_focus": "ㅊ",
       "articulation_tip": "혀끝을 윗잇몸 근처에 두고, 공기를 짧게 터뜨리듯 발음해보세요."}
    ]
  }
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..conversation.llm import LLM


PRONUNCIATION_SYSTEM = (
    "당신은 한국어 발음·조음 코치다. 사용자의 발화 transcript와 각 발화의 길이(초)를 보고, "
    "발음이 뭉개졌을 가능성이 가장 높은 단어 최대 3개를 골라 각각 (a) 초점 자모 1개와 "
    "(b) 조음점에 기반한 텍스트 가이드를 작성하라. 가이드는 시각적 비유 없이 혀·입술·공기 흐름의 "
    "구체적인 동작으로만 설명한다."
)


def _user_turn_samples(turns: list[Any]) -> list[dict]:
    """LLM에 넘길 사용자 턴 요약: turn_index, text, 대략적인 길이(초)."""
    samples: list[dict] = []
    for t in turns:
        if getattr(t, "speaker", None) != "user":
            continue
        text = (
            getattr(t, "transcript_verbatim", None)
            or getattr(t, "transcript", None)
            or ""
        )
        if not text.strip():
            continue
        s = getattr(t, "start_ts_ms", None)
        e = getattr(t, "end_ts_ms", None)
        sec = round((e - s) / 1000.0, 2) if (s is not None and e is not None and e > s) else None
        samples.append(
            {"turn_index": int(getattr(t, "turn_index", 0)), "text": text, "sec": sec}
        )
    return samples


async def analyze_pronunciation(turns: list[Any], llm: "LLM") -> dict:
    """LLM에 사용자 턴을 보여주고 weak_words 후보 최대 3개를 받는다.

    실패 시(또는 비어있을 때) `{"weak_words": []}`를 안전하게 반환.
    """
    samples = _user_turn_samples(turns)
    if not samples:
        return {"weak_words": []}

    payload = {"turns": samples}
    user = (
        "다음 사용자 발화에서 발음이 가장 뭉개졌을 가능성이 높은 단어 최대 3개를 골라, "
        "각각 초점 자모(phoneme_focus, 자음/모음 1개)와 조음점 기반 articulation_tip(한국어 1~2문장)을 채워라. "
        "약점 없으면 빈 배열을 반환하라.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    schema = {
        "weak_words": (
            "[{turn_index:int, word:str, phoneme_focus:str(자모 1개), "
            "articulation_tip:str(조음점 가이드 1~2문장)}] 최대 3개"
        )
    }
    res = await llm.chat_json(PRONUNCIATION_SYSTEM, user, schema)
    weak = (res or {}).get("weak_words") or []
    cleaned: list[dict] = []
    seen_words: set[tuple[int, str]] = set()
    for item in weak:
        if not isinstance(item, dict):
            continue
        try:
            entry = {
                "turn_index": int(item.get("turn_index", -1)),
                "word": str(item.get("word") or "").strip(),
                "phoneme_focus": str(item.get("phoneme_focus") or "").strip(),
                "articulation_tip": str(item.get("articulation_tip") or "").strip(),
            }
        except (TypeError, ValueError):
            continue
        if not entry["word"] or not entry["articulation_tip"]:
            continue
        key = (entry["turn_index"], entry["word"])
        if key in seen_words:
            continue
        seen_words.add(key)
        cleaned.append(entry)
        if len(cleaned) >= 3:
            break
    return {"weak_words": cleaned}
