"""End-to-end analysis pipeline with mock adapters — no real API calls (§8)."""
import asyncio
import json

import numpy as np
import soundfile as sf

from app import situations
from app.analysis.pipeline import run_analysis
from app.config import RESULTS_DIR
from app.conversation.llm import MockLLM
from app.conversation.stt import MockSTT
from app.db import SessionLocal, init_db
from app.models import RecommendedRewrite, Session, Turn

SR = 16000

# (speaker, turn_index, start_ms, end_ms, text)
_BAD = [
    ("ai", 0, 0, 1500, "우리 진짜 여기서 끝인 거야?"),
    ("user", 1, 2000, 5000, "음 어 그 글쎄 잘 모르겠어 그냥 막 뭐 어쨌든 딱히 할 말이 없어"),
    ("ai", 2, 5500, 7000, "그게 다야? 진심이 안 느껴져."),
    ("user", 3, 7500, 10000, "어 그냥 좀 막 뭐 그래 딱히 더 할 얘기는 없는 것 같아"),
]
_GOOD = [
    ("ai", 0, 0, 1500, "우리 진짜 여기서 끝인 거야?"),
    ("user", 1, 2000, 5000, "응 이제 우리는 여기서 분명하게 마무리하는 게 맞다고 생각해"),
    ("ai", 2, 5500, 7000, "그게 다야? 진심이 안 느껴져."),
    ("user", 3, 7500, 10000, "그동안 진심으로 고마웠어 너도 나도 더 좋은 사람으로 잘 지내길 바라"),
]


def _write_silent(path, start_ms, end_ms):
    n = max(1, int((end_ms - start_ms) / 1000.0 * SR))
    sf.write(str(path), np.zeros(n, dtype="float32"), SR)


def _make_session(db, tmp_dir, turns_spec, goal="clear_closure"):
    tmp_dir.mkdir(parents=True, exist_ok=True)
    s = Session(situation_id="breakup_last_conversation", goal_id=goal)
    db.add(s)
    db.flush()
    for speaker, idx, start, end, text in turns_spec:
        wav = tmp_dir / f"turn_{idx:02d}_{speaker}.wav"
        _write_silent(wav, start, end)
        if speaker == "user":
            wav.with_name(wav.stem + ".transcript.json").write_text(
                json.dumps({"text": text, "text_verbatim": text}, ensure_ascii=False),
                encoding="utf-8",
            )
        db.add(
            Turn(
                session_id=s.id,
                turn_index=idx,
                speaker=speaker,
                audio_path=str(wav),
                start_ts_ms=start,
                end_ts_ms=end,
                transcript=text,
                transcript_verbatim=text,
            )
        )
    db.commit()
    return s.id


def test_pipeline_runs_end_to_end_with_mocks(tmp_path):
    init_db()
    db = SessionLocal()
    situations.sync_situations_to_db(db)
    sid = _make_session(db, tmp_path, _BAD)
    db.close()

    analysis = asyncio.run(run_analysis(sid, stt=MockSTT(), llm=MockLLM()))

    # judge dimensions populated and in range
    for dim in ("flow_coherence", "flow_consistency", "flow_goal_alignment",
                "flow_avoidance", "topic_adherence", "recovery_score"):
        val = getattr(analysis, dim)
        assert val is not None and 1.0 <= val <= 5.0, dim

    # 3 internal judge runs (H1 plumbing)
    assert len(analysis.judge_runs["flow"]) == 3
    assert analysis.judge_variance["report"]["pass"] is True  # mock is deterministic

    # signal + filler metrics
    assert analysis.spm_mean > 0
    assert analysis.filler_count >= 1  # the bad turns are full of fillers
    assert 0.0 <= analysis.vocab_mattr <= 1.0

    # rewrites persisted + JSON dumped
    db = SessionLocal()
    n_rewrites = db.query(RecommendedRewrite).filter_by(session_id=sid).count()
    db.close()
    assert n_rewrites >= 1
    assert (RESULTS_DIR / f"{sid}.json").exists()


def test_pipeline_scores_good_above_bad(tmp_path):
    init_db()
    db = SessionLocal()
    situations.sync_situations_to_db(db)
    bad_id = _make_session(db, tmp_path / "bad", _BAD)
    good_id = _make_session(db, tmp_path / "good", _GOOD)
    db.close()

    bad = asyncio.run(run_analysis(bad_id, stt=MockSTT(), llm=MockLLM()))
    good = asyncio.run(run_analysis(good_id, stt=MockSTT(), llm=MockLLM()))

    assert good.flow_coherence >= bad.flow_coherence
    assert good.filler_count <= bad.filler_count
