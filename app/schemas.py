"""Pydantic v2 request/response schemas for the API (§6)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- content / situations ----------
SituationCategory = Literal["emotional", "interview", "presentation", "business"]


class GoalOptionOut(BaseModel):
    id: str
    label: str
    eval_focus: list[str] = Field(default_factory=list)


class SituationOut(BaseModel):
    id: str
    title: str
    opening_line: str
    duration_target_sec: list[int]
    goal_options: list[GoalOptionOut]
    # v3 신규: 카탈로그 분류 & 난이도. 기존 호출자 호환을 위해 기본값 제공.
    category: SituationCategory = "emotional"
    difficulty: int = 1


# ---------- sessions ----------
class SessionCreateIn(BaseModel):
    situation_id: str
    goal_id: str


class SessionCreateOut(BaseModel):
    session_id: str
    opening_audio_url: Optional[str] = None
    opening_text: str


class TurnOut(BaseModel):
    ai_text: str
    ai_audio_url: Optional[str] = None
    transcript: str


class EndOut(BaseModel):
    analysis_job_id: str


class RetakeIn(BaseModel):
    mode: Literal["situation"] = "situation"


class RetakeOut(BaseModel):
    new_session_id: str


# ---------- analysis ----------
class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal["pending", "ready"] = "ready"
    session_id: Optional[str] = None

    flow_coherence: Optional[float] = None
    flow_consistency: Optional[float] = None
    flow_goal_alignment: Optional[float] = None
    flow_avoidance: Optional[float] = None
    vocab_mattr: Optional[float] = None
    sentence_length_stdev: Optional[float] = None

    latency_p50_ms: Optional[float] = None
    latency_p90_ms: Optional[float] = None
    filler_count: Optional[int] = None
    filler_density: Optional[float] = None
    topic_adherence: Optional[float] = None
    recovery_score: Optional[float] = None

    spm_mean: Optional[float] = None
    spm_stdev: Optional[float] = None
    f0_mean: Optional[float] = None
    f0_stdev: Optional[float] = None
    silence_ratio: Optional[float] = None
    tail_clarity: Optional[float] = None

    # v3 — 답변 길이
    answer_length_syllable_mean: Optional[float] = None
    answer_length_sec_mean: Optional[float] = None
    answer_length_sec_stdev: Optional[float] = None
    too_long_turn_count: Optional[int] = None

    judge_runs: Optional[Any] = None
    judge_variance: Optional[Any] = None


class PendingOut(BaseModel):
    status: Literal["pending"] = "pending"


class RewriteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    source_turn_id: Optional[str] = None
    original_text: str
    rewrites: Optional[Any] = None


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    baseline_session_id: str
    retake_session_id: str
    better_side: str
    diff_summary: Optional[Any] = None
    llm_verdict: Optional[str] = None
