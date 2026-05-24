"""Analysis pipeline (§5.5). Orchestrates the full session analysis and persists
both a SessionAnalysis row and a JSON dump under data/results/.

Runs in the background after a session ends; clients poll GET /sessions/{id}/analysis.
"""
from __future__ import annotations

import json
import re
import statistics
from typing import TYPE_CHECKING, Any, Optional

from ..config import RESULTS_DIR
from ..conversation.llm import get_llm
from ..conversation.stt import get_stt
from ..db import session_scope
from ..models import RecommendedRewrite, Session, SessionAnalysis
from ..situations import load_situation
from .compare import compare_sessions
from .fillers import analyze_fillers
from .judge import judge_flow, judge_improv, judge_variance_report
from .rewrite import recommend_rewrites
from .signal_metrics import (
    compute_answer_lengths,
    compute_session_delivery,
    resolve_answer_length_threshold_sec,
)
from .transcript import reprocess_verbatim

if TYPE_CHECKING:
    from ..conversation.llm import LLM
    from ..conversation.stt import STT

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_MATTR_WINDOW = 25
_kiwi = None  # lazily-created singleton


# --------------------------------------------------------------------------- #
# vocabulary / structure (step 5)
# --------------------------------------------------------------------------- #
def _morphemes(text: str) -> list[str]:
    global _kiwi
    try:
        if _kiwi is None:
            from kiwipiepy import Kiwi

            _kiwi = Kiwi()
        return [tok.form for tok in _kiwi.tokenize(text) if tok.form.strip()]
    except Exception:
        return _TOKEN_RE.findall(text)


def _mattr(tokens: list[str], window: int = _MATTR_WINDOW) -> float:
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return round(len(set(tokens)) / len(tokens), 4)
    ratios = [
        len(set(tokens[i : i + window])) / window
        for i in range(len(tokens) - window + 1)
    ]
    return round(statistics.fmean(ratios), 4)


def _vocab_structure(user_text: str) -> dict:
    tokens = _morphemes(user_text)
    sentences = [s for s in re.split(r"[.!?\n]+", user_text) if s.strip()]
    sent_lens = [len(_TOKEN_RE.findall(s)) for s in sentences]
    stdev = (
        round(statistics.pstdev(sent_lens), 3) if len(sent_lens) > 1 else 0.0
    )
    return {
        "vocab_mattr": _mattr(tokens),
        "sentence_length_stdev": stdev,
        "n_tokens": len(tokens),
        "n_types": len(set(tokens)),
        "n_sentences": len(sentences),
    }


# --------------------------------------------------------------------------- #
# main orchestration
# --------------------------------------------------------------------------- #
async def run_analysis(
    session_id: str, stt: "STT | None" = None, llm: "LLM | None" = None
) -> SessionAnalysis:
    stt = stt or get_stt()
    llm = llm or get_llm()

    with session_scope() as db:
        session = db.get(Session, session_id)
        if session is None:
            raise ValueError(f"unknown session: {session_id}")
        turns = list(session.turns)
        user_turns = [t for t in turns if t.speaker == "user"]

        # 2. verbatim STT re-processing
        transcripts = await reprocess_verbatim(session, stt)

        # 3. signal metrics (SPM / F0 / silence / tail / latency)
        delivery = compute_session_delivery(turns)

        # 3b. v3: 답변 길이 — 카테고리(=상황 YAML)별 임계값으로 too_long 판정
        try:
            situation = load_situation(session.situation_id)
        except KeyError:
            situation = {}
        ans_threshold = resolve_answer_length_threshold_sec(
            situation.get("category"),
            situation.get("answer_length_guideline_sec"),
        )
        answer_lengths = compute_answer_lengths(turns, threshold_sec=ans_threshold)

        # 4. fillers — aggregate over user turns
        total_fillers, total_tokens, filler_details = 0, 0, []
        for t in user_turns:
            tr = transcripts.get(t.id)
            text = (tr.text if tr else None) or t.transcript_verbatim or t.transcript or ""
            words = tr.words if tr else None
            fa = await analyze_fillers(text, words, llm)
            total_fillers += fa["count"]
            total_tokens += fa["n_tokens"]
            filler_details.append({"turn_id": t.id, **fa})
        filler_density = round(total_fillers / total_tokens, 4) if total_tokens else 0.0

        # 5. vocabulary / structure
        user_text = "\n".join(
            (t.transcript_verbatim or t.transcript or "") for t in user_turns
        )
        vocab = _vocab_structure(user_text)

        # 6. LLM-as-judge (3 runs each)
        flow = await judge_flow(session, llm)
        improv = await judge_improv(session, llm)
        variance = judge_variance_report(flow.runs + improv.runs)

        # assemble the analysis row
        analysis = SessionAnalysis(
            session_id=session.id,
            flow_coherence=flow.mean.get("coherence"),
            flow_consistency=flow.mean.get("consistency"),
            flow_goal_alignment=flow.mean.get("goal_alignment"),
            flow_avoidance=flow.mean.get("avoidance"),
            vocab_mattr=vocab["vocab_mattr"],
            sentence_length_stdev=vocab["sentence_length_stdev"],
            latency_p50_ms=delivery["p50_ms"],
            latency_p90_ms=delivery["p90_ms"],
            filler_count=total_fillers,
            filler_density=filler_density,
            topic_adherence=improv.mean.get("topic_adherence"),
            recovery_score=improv.mean.get("recovery"),
            spm_mean=delivery["spm_mean"],
            spm_stdev=delivery["spm_stdev"],
            f0_mean=delivery["f0_mean"],
            f0_stdev=delivery["f0_stdev"],
            silence_ratio=delivery["silence_ratio"],
            tail_clarity=delivery["tail_clarity"],
            # v3 — 답변 길이
            answer_length_syllable_mean=answer_lengths["syllable_mean"],
            answer_length_sec_mean=answer_lengths["sec_mean"],
            answer_length_sec_stdev=answer_lengths["sec_stdev"],
            too_long_turn_count=len(answer_lengths["too_long_turns"]),
            judge_runs={"flow": flow.runs, "improv": improv.runs},
            judge_variance={
                "flow": flow.stdev,
                "improv": improv.stdev,
                "report": variance,
            },
        )

        # 7. improvement rewrites (uses the freshly-scored analysis)
        rewrites = await recommend_rewrites(session, analysis, llm)

        # 8. persist + JSON dump
        payload = _build_payload(
            session, analysis, delivery, vocab, filler_details, variance, answer_lengths
        )
        payload["rewrites"] = [
            {"source_turn_id": r.source_turn_id, "original_text": r.original_text, "variants": r.rewrites}
            for r in rewrites
        ]
        analysis.raw_payload = payload

        db.merge(analysis)
        db.query(RecommendedRewrite).filter_by(session_id=session.id).delete()
        for r in rewrites:
            db.add(r)

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{session.id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # `analysis` is a transient copy (merge created the managed one); its
        # plain-Python attributes remain usable after the session closes.
        return analysis


async def analyze_and_compare(
    session_id: str, stt: "STT | None" = None, llm: "LLM | None" = None
) -> SessionAnalysis:
    """Run analysis and, if this is a retake whose parent is already analyzed,
    persist a RetakeComparison (so GET /comparisons/{id} works via the API)."""
    llm = llm or get_llm()
    analysis = await run_analysis(session_id, stt=stt, llm=llm)
    with session_scope() as db:
        session = db.get(Session, session_id)
        if session and session.parent_session_id:
            parent = db.get(Session, session.parent_session_id)
            parent_an = db.get(SessionAnalysis, session.parent_session_id)
            if parent is not None and parent_an is not None:
                comparison = await compare_sessions(parent, session, llm)
                db.add(comparison)
    return analysis


def _build_payload(
    session, analysis, delivery, vocab, filler_details, variance, answer_lengths
) -> dict:
    return {
        "session_id": session.id,
        "situation_id": session.situation_id,
        "goal_id": session.goal_id,
        "parent_session_id": session.parent_session_id,
        "metrics": {
            "flow": {
                "coherence": analysis.flow_coherence,
                "consistency": analysis.flow_consistency,
                "goal_alignment": analysis.flow_goal_alignment,
                "avoidance": analysis.flow_avoidance,
                "vocab_mattr": analysis.vocab_mattr,
                "sentence_length_stdev": analysis.sentence_length_stdev,
            },
            "improv": {
                "latency_p50_ms": analysis.latency_p50_ms,
                "latency_p90_ms": analysis.latency_p90_ms,
                "filler_count": analysis.filler_count,
                "filler_density": analysis.filler_density,
                "topic_adherence": analysis.topic_adherence,
                "recovery_score": analysis.recovery_score,
            },
            "delivery": {
                "spm_mean": analysis.spm_mean,
                "spm_stdev": analysis.spm_stdev,
                "f0_mean": analysis.f0_mean,
                "f0_stdev": analysis.f0_stdev,
                "silence_ratio": analysis.silence_ratio,
                "tail_clarity": analysis.tail_clarity,
            },
            "answer_length": {
                "syllable_mean": analysis.answer_length_syllable_mean,
                "sec_mean": analysis.answer_length_sec_mean,
                "sec_stdev": analysis.answer_length_sec_stdev,
                "too_long_turn_count": analysis.too_long_turn_count,
                "threshold_sec": answer_lengths.get("threshold_sec"),
                "per_turn": answer_lengths.get("per_turn", []),
                "too_long_turns": answer_lengths.get("too_long_turns", []),
            },
        },
        "vocab": vocab,
        "fillers": filler_details,
        "judge": {
            "runs": analysis.judge_runs,
            "variance": variance,
        },
    }
