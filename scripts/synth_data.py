"""Synthetic session generator (§5.4) — the most important script.

Claude writes an 8-20 turn Korean dialogue for a (situation, goal, quality),
OpenAI TTS renders each turn to WAV (AI vs. user voice), and a Session + Turns
are inserted into the DB. With --mock everything is deterministic and offline.

    python scripts/synth_data.py --situation breakup_last_conversation \
        --goal clear_closure --quality good --out data/audio/session_001
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# --- make the project root importable, honor --mock before app import ---------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "--mock" in sys.argv:
    os.environ["USE_MOCKS"] = "1"

from app.constants import AI_VOICE, USER_VOICE  # noqa: E402
from app.conversation.llm import get_llm  # noqa: E402
from app.conversation.tts import get_tts  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.models import Session, Turn  # noqa: E402
from app.situations import goal_for, load_situation, sync_situations_to_db  # noqa: E402

MAX_TURNS = 20

SCRIPT_SYSTEM = (
    "당신은 한국어 대화 시나리오 작가다. 주어진 상황과 목표에 맞는 현실적인 연습 대화를 쓴다. "
    "각 발화는 1~3문장의 자연스러운 구어체로 작성한다."
)

_QUALITY_NOTE = {
    "good": "사용자 발화는 군말 없이 다듬어지고, 목표에 또렷하게 부합하도록 작성하라.",
    "bad": (
        "사용자 발화에 필러 단어(음/어/그/막/그냥/뭐)를 자주 섞고, "
        "직접적인 답을 회피하며 둘러말하는 식으로 작성하라. 검증 신호가 분명해지도록 과장해도 좋다."
    ),
    "mixed": "사용자 발화 중 일부는 다듬어지고 일부는 군말·회피가 섞이도록 번갈아 작성하라.",
}

# v3 Step 9: bad 모드에 카테고리별 패턴을 덧붙여 H5(코칭 카드) 검증 신호를 강화.
_BAD_CATEGORY_NOTE = {
    "emotional": (
        " 정서 상황답게 필러를 많이 섞고, 본심을 회피하며 둘러말하라. "
        "끝음을 흐리게 마무리하라."
    ),
    "interview": (
        " 면접 답변은 결론 없이 장황하게, 두서없이 이어가라. "
        "한 답변이 길어지도록(STAR의 Action·Result 부분을 늘어놓듯) 늘어뜨려라. "
        "결론은 끝까지 등장시키지 말라."
    ),
    "presentation": (
        " 발표는 청자(임원)의 관심사를 무시하고 기술 디테일에 몰두하라. "
        "각 문장의 끝을 흐리게 말끝 흐리듯 마무리하라."
    ),
    "business": (
        " 비즈니스 요청은 핵심부터 말하지 말고 배경설명을 길게 늘어놓아라. "
        "결론은 가장 마지막에만 짧게 언급하라."
    ),
}


def _dur_ms(path: Path) -> int:
    import soundfile as sf

    try:
        info = sf.info(str(path))
        return int(info.frames / info.samplerate * 1000)
    except Exception:
        return 0


def _quality_note(quality: str, category: str | None) -> str:
    base = _QUALITY_NOTE.get(quality, _QUALITY_NOTE["good"])
    if quality == "bad" and category:
        return base + _BAD_CATEGORY_NOTE.get(category, "")
    return base


def _build_user(situation: dict, goal: dict, quality: str) -> str:
    category = situation.get("category")
    payload = {
        "situation_id": situation["id"],
        "title": situation["title"],
        "goal": goal["label"],
        "eval_focus": goal.get("eval_focus", []),
        "quality": quality,
        "category": category,
    }
    return (
        f"상황: {situation['title']} (카테고리: {category or 'emotional'})\n"
        f"AI 페르소나:\n{situation['ai_persona']}\n"
        f"AI의 첫 발화(이미 말했음): {situation['opening_line']}\n"
        f"사용자의 목표: {goal['label']} (포커스: {', '.join(goal.get('eval_focus', []))})\n"
        f"작성 지침: {_quality_note(quality, category)}\n"
        "위 'AI의 첫 발화' 다음의 사용자 발화부터 시작해, user와 ai가 번갈아 말하는 "
        "8~16턴 대화를 작성하라.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


async def synth_session(
    situation_id: str,
    goal_id: str,
    quality: str,
    out_dir: str | Path,
    *,
    llm=None,
    tts=None,
) -> str:
    init_db()
    with session_scope() as db:
        sync_situations_to_db(db)

    situation = load_situation(situation_id)
    goal = goal_for(situation_id, goal_id)
    llm = llm or get_llm()
    tts = tts or get_tts()

    # 1. generate the dialogue script
    schema = {
        "dialogue": "[{\"speaker\": \"user\"|\"ai\", \"text\": str}, ...] 배열 (사용자 발화부터 시작)"
    }
    res = await llm.chat_json(SCRIPT_SYSTEM, _build_user(situation, goal, quality), schema)
    dialogue = [d for d in (res or {}).get("dialogue", []) if d.get("text")]
    if len(dialogue) < 2:
        print("WARNING: LLM returned a very short dialogue; proceeding anyway.", file=sys.stderr)

    # opening AI line (from YAML) + generated turns, capped at MAX_TURNS
    full = [{"speaker": "ai", "text": situation["opening_line"]}]
    full += [{"speaker": d["speaker"], "text": d["text"]} for d in dialogue]
    full = full[:MAX_TURNS]

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 2-5. render audio, build timeline, persist
    cursor = 0
    meta_turns = []
    with session_scope() as db:
        session = Session(situation_id=situation_id, goal_id=goal_id)
        db.add(session)
        db.flush()
        session_id = session.id

        for i, turn in enumerate(full):
            spk, text = turn["speaker"], turn["text"]
            voice = AI_VOICE if spk == "ai" else USER_VOICE
            wav = out_path / f"turn_{i:02d}_{spk}.wav"
            await tts.synthesize(text, voice, wav)
            dur = _dur_ms(wav)
            start, end = cursor, cursor + dur

            db.add(
                Turn(
                    session_id=session_id,
                    turn_index=i,
                    speaker=spk,
                    audio_path=str(wav),
                    start_ts_ms=start,
                    end_ts_ms=end,
                    transcript=text,
                    transcript_verbatim=text if spk == "user" else None,
                )
            )
            if spk == "user":  # sidecar lets MockSTT recover the text in analysis
                wav.with_name(wav.stem + ".transcript.json").write_text(
                    json.dumps({"text": text, "text_verbatim": text}, ensure_ascii=False),
                    encoding="utf-8",
                )
            meta_turns.append(
                {
                    "turn_index": i,
                    "speaker": spk,
                    "text": text,
                    "audio": wav.name,
                    "start_ts_ms": start,
                    "end_ts_ms": end,
                }
            )

            # gap to next turn: an AI→user transition becomes the user's response latency
            nxt = full[i + 1]["speaker"] if i + 1 < len(full) else None
            gap = 500 + (i * 37) % 500 if (spk == "ai" and nxt == "user") else 300
            cursor = end + gap

        session.duration_sec = round(cursor / 1000.0, 2)

        (out_path / "session.json").write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "situation_id": situation_id,
                    "goal_id": goal_id,
                    "quality": quality,
                    "duration_sec": session.duration_sec,
                    "turns": meta_turns,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return session_id


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a synthetic AEIOU session.")
    p.add_argument("--situation", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--quality", choices=["good", "bad", "mixed"], default="good")
    p.add_argument(
        "--category",
        choices=["emotional", "interview", "presentation", "business"],
        help=(
            "참고용 카테고리 힌트. 일반적으로 situation YAML이 이미 category를 갖고 있으므로 "
            "지정하지 않아도 됨. 지정 시 YAML 값을 덮어쓰는 게 아니라 일관성만 확인한다."
        ),
    )
    p.add_argument("--out", required=True, help="output dir, e.g. data/audio/session_001")
    p.add_argument("--mock", action="store_true", help="force deterministic offline mocks")
    args = p.parse_args()

    # category 인자는 일관성 확인용. 실제 dialogue는 YAML의 category를 사용한다.
    if args.category is not None:
        from app.situations import load_situation  # noqa: PLC0415

        yaml_cat = load_situation(args.situation).get("category")
        if yaml_cat and yaml_cat != args.category:
            print(
                f"WARNING: --category={args.category} but YAML says {yaml_cat}. "
                "YAML wins.",
                file=sys.stderr,
            )

    session_id = asyncio.run(
        synth_session(args.situation, args.goal, args.quality, args.out)
    )
    n_turns = len(json.loads((Path(args.out) / "session.json").read_text(encoding="utf-8"))["turns"])
    print(f"session_id={session_id}")
    print(f"out={args.out}  turns={n_turns}  quality={args.quality}  mocks={os.environ.get('USE_MOCKS') == '1'}")


if __name__ == "__main__":
    main()
