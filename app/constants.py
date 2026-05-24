"""Shared constants (single source of truth, no heavy imports)."""
from __future__ import annotations

# Korean filler lexicon (§5.3). Dictionary-matched candidates.
FILLER_DICT: set[str] = {
    "음", "어", "그", "뭐", "약간", "좀", "그냥", "있잖아", "아니", "막",
}

# Polysemous words: never auto-counted as filler from the dictionary alone;
# they are candidates ONLY and must be confirmed by the LLM in context.
POLYSEMOUS: set[str] = {"그", "좀", "막", "뭐", "아니"}

# Unambiguous fillers: dictionary match is strong evidence on its own.
STRONG_FILLERS: set[str] = FILLER_DICT - POLYSEMOUS

# Avoidance / hedging markers — used by the mock judge heuristic and (as hints)
# by the real judge prompt to gauge how much the speaker dodges the point.
AVOID_MARKERS: tuple[str, ...] = (
    "글쎄", "잘 모르겠", "모르겠어", "딱히", "나중에", "어쨌든", "아무튼",
    "뭐 그냥", "그런 것 같기도", "별로", "그게 좀",
)

# TTS voices (OpenAI gpt-4o-mini-tts) used by synth_data: AI vs. user speaker.
AI_VOICE = "nova"
USER_VOICE = "echo"
