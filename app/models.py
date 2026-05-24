"""SQLAlchemy 2.x ORM models (§5.1).

SQLite-first but Postgres-compatible: string UUID PKs, JSON columns, explicit
FKs. Initialized via Base.metadata.create_all (no Alembic — PoC).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Situation(Base):
    __tablename__ = "situations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # snake_case
    title: Mapped[str] = mapped_column(String(255))
    yaml_path: Mapped[str] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    situation_id: Mapped[str] = mapped_column(ForeignKey("situations.id"))
    goal_id: Mapped[str] = mapped_column(String(64))
    parent_session_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("sessions.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session",
        order_by="Turn.turn_index",
        cascade="all, delete-orphan",
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    turn_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(8))  # 'user' | 'ai'
    audio_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    start_ts_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_ts_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_verbatim: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session: Mapped["Session"] = relationship(back_populates="turns")


class SessionAnalysis(Base):
    __tablename__ = "session_analyses"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), primary_key=True)

    # 표현 흐름 (flow)
    flow_coherence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    flow_consistency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    flow_goal_alignment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    flow_avoidance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vocab_mattr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentence_length_stdev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 즉흥 대응 (improv)
    latency_p50_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_p90_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    filler_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    filler_density: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    topic_adherence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recovery_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 전달력 (delivery)
    spm_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spm_stdev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f0_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f0_stdev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    silence_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tail_clarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # v3: 답변 길이 (카테고리별 임계값 초과 카운트 포함)
    answer_length_syllable_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    answer_length_sec_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    answer_length_sec_stdev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    too_long_turn_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # v3: 반복 표현 (필러와 분리; 사용자 고유 n-gram 빈도)
    repeated_phrase_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    repetition_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # v3: 발음 분석 (텍스트 가이드 only) — {"weak_words": [...]} JSON
    pronunciation_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    # 메타
    judge_runs: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    judge_variance: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    raw_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RecommendedRewrite(Base):
    __tablename__ = "recommended_rewrites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    source_turn_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("turns.id"), nullable=True
    )
    original_text: Mapped[str] = mapped_column(Text)
    rewrites: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)


class RetakeComparison(Base):
    __tablename__ = "retake_comparisons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    baseline_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    retake_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    better_side: Mapped[str] = mapped_column(String(16))  # 'baseline'|'retake'|'tie'
    diff_summary: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    llm_verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
