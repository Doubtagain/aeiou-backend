"""Lightweight data carriers shared across adapters and the analysis pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)
    language: str = "ko"


@dataclass
class Message:
    role: str  # 'user' | 'assistant'
    content: str
