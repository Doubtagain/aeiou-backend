# VoiceUp PoC

한국어 대화 코칭 서비스 **VoiceUp**의 가설 검증용 PoC 백엔드. 사용자가 일상 상황(이별·사과·고백·갈등·거절)을 골라 AI와 음성 대화를 한 뒤, **표현 흐름·즉흥 대응·전달력**에 대한 코칭 리포트를 받는다.

> 이 코드의 목적은 "보이는 것"을 만드는 게 아니라 **가설(H1~H4)을 검증**하는 것이다. 전체 설계는 [`SPEC.md`](./SPEC.md) 참조.

## 빠른 시작

```bash
# 1. 의존성 설치
pip install -r requirements.txt           # (uv 사용 시: uv sync)

# 2. (실 API 검증 시) 환경변수 설정
cp .env.example .env                       # ANTHROPIC_API_KEY, OPENAI_API_KEY 입력

# 3. 합성 세션 생성 (실 API)
python scripts/synth_data.py --situation breakup_last_conversation \
    --goal clear_closure --quality good --out data/audio/demo

# 4. API 서버 실행
uvicorn app.main:app --reload              # http://127.0.0.1:8000/docs

# 5. 전체 플로우 1회 시연 (실 API)
python scripts/demo_run.py
```

키 없이 전 구간을 오프라인으로 돌리려면 모든 명령에 `--mock`을 붙이거나 `USE_MOCKS=1`을 설정한다.

## 테스트

```bash
pytest        # 외부 API 호출 없이 모킹으로 통과 (현재 11 passed in ~3.7s)
```

## 가설별 검증 방법

| 가설 | 검증 명령 | 합격 기준 |
|---|---|---|
| **H1.** LLM-judge가 일관된 점수를 낸다 | `python scripts/eval_judge_variance.py --runs 5` | 각 평가 차원 표준편차 **≤ 0.7** (5점 척도) |
| **H2.** 필러·운율·페이싱 지표가 합리적이다 | `python scripts/demo_run.py` 후 `data/results/*.json` 검토 | SPM **200~500**, F0 **80~300Hz**, silence_ratio **0.1~0.4** |
| **H3.** 개선 문장이 원의도 유지+목표 부합 | `GET /sessions/{id}/rewrites` 결과 정성 평가 (아래 표) | (정성) 원의도 유지하며 목표에 더 부합 |
| **H4.** 리테이크 비교가 의미 있는 차이를 잡는다 | `python scripts/eval_retake_diff.py` | `better_side == "retake"` 이고 verdict에 "개선" 포함 |

각 모듈은 위 가설 중 하나에 대응한다:
`analysis/judge.py`→H1, `analysis/signal_metrics.py`+`fillers.py`→H2, `analysis/rewrite.py`→H3, `analysis/compare.py`→H4.

## 합격 기준 (성공 정의, §12)

1. `pytest`가 **실 API 호출 없이** 통과 → ✅ **충족** (11 passed, ~3.7s, 전부 Mock)
2. `python scripts/demo_run.py`가 **실 API로** 끝까지 돌아 분석 JSON·비교 verdict 출력 → ⏳ **미실행** (아래 참조)
3. `eval_judge_variance.py`·`eval_retake_diff.py` 결과가 합격 기준 충족 → ⏳ **미실행** (아래 참조)

## 검증 결과

### ✅ 자동화 테스트 (실 API 0회)

```
$ pytest
11 passed in 3.70s
```
- `test_fillers` — 사전 매칭 + 다의어 처리(의미로 쓰인 "그"는 필러로 분류되지 않음)
- `test_signal_metrics` — 1초 사인파(150Hz)에서 F0≈150, SPM/침묵/끝음/지연 합리적 범위
- `test_pipeline` — MockSTT/MockLLM/MockTTS로 분석 파이프라인 전 구간 통과, good ≥ bad 방향성

### ⏳ 실 API 검증 — 이 환경에서는 미실행 (정직한 현황)

이 저장소가 만들어진 환경에는 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`가 **설정되어 있지 않아**, 실 API를 사용하는 `demo_run.py`·`eval_*.py`를 **실제로 돌리지 못했다.** 따라서 위 합격 기준 2·3의 실측 수치는 비어 있다. 키를 넣고 아래를 실행하면 채워진다.

```bash
# 키 설정 후
python scripts/demo_run.py
python scripts/eval_judge_variance.py --runs 5
python scripts/eval_retake_diff.py
```

대신 **모킹 모드 스모크**로 전 파이프라인이 끝까지 도는 것과 신호의 *방향성*은 확인했다(아래는 `--mock` 결과로, H1/H4를 "검증"한 것이 아니라 배관이 동작함을 보인 것이다):

| 항목 | `--mock` 관측값 | 비고 |
|---|---|---|
| demo_run better_side | `retake` (=다듬은 good) | 비교 로직 정상 |
| bad 세션 filler_count / density | 11 / 0.275 | 필러 검출 정상 |
| bad 세션 SPM | ~405 (H2 범위 내) | 텍스트 길이 비례 무음 오디오 기준 |
| 응답 latency p50 | ~611ms | 합성 타임라인 기준 |
| eval_judge_variance | 모든 차원 stdev=0 → PASS | **Mock은 결정론적**이라 분산 0. 실제 H1은 실 API에서만 의미 |
| eval_retake_diff | better=retake, "개선" 포함 → PASS | good>bad 방향성 |

> **F0/silence/tail_clarity는 모킹(무음 WAV)에서 의미가 없다** (각각 0/1.0/0). H2의 운율 지표는 **실 TTS 오디오**로 `demo_run.py`를 돌려야 검증된다. SPM·필러·지연·MATTR은 모킹에서도 유효하다.

### H3 재작성 예시 (`--mock` 산출, 정성 평가용 양식)

| 원본(사용자) | 재작성 v1 | 재작성 v2 |
|---|---|---|
| "음 그냥 뭐 잘 모르겠어" | "잘 모르겠어" (군말 제거) | "솔직히 말하면, 잘 모르겠어" (감정 노출 강화) |

실제 품질은 실 Claude로 `GET /sessions/{id}/rewrites`를 호출해 평가할 것. (Mock은 군말 제거 + 정형 변형만 수행)

## API 엔드포인트 (§6)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/situations` | 상황 카탈로그 |
| POST | `/sessions` | 세션 생성 → `{session_id, opening_audio_url, opening_text}` |
| POST | `/sessions/{id}/turn` | multipart(audio+turn_index) → `{ai_text, ai_audio_url, transcript}` |
| POST | `/sessions/{id}/end` | 분석을 백그라운드 시작 → `{analysis_job_id}` |
| GET | `/sessions/{id}/analysis` | `SessionAnalysis` 또는 `{status:"pending"}` |
| GET | `/sessions/{id}/rewrites` | `[RecommendedRewrite]` |
| POST | `/sessions/{id}/retake` | `{mode}` → `{new_session_id}` |
| GET | `/comparisons/{retake_session_id}` | `RetakeComparison` |

오디오는 `/static/audio/...`로 정적 서빙. WebSocket 스트리밍은 비범위(POST 턴으로 갈음).

## 아키텍처

- **스택**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x (SQLite, `create_all`).
- **외부 어댑터**(`app/conversation/`): STT(Whisper `whisper-1`)·LLM(Claude `claude-sonnet-4-6`)·TTS(OpenAI `gpt-4o-mini-tts`)는 모두 Protocol 뒤에 숨고, **실 구현 + 결정론적 Mock**을 둔다. `USE_MOCKS=1` 또는 키 부재 시 자동으로 Mock.
  - Mock 규약: `chat_json(system, user, schema)`에서 `user`에 임베드된 JSON을 읽고 `schema` 키로 작업(judge/fillers/rewrite/compare/dialogue)을 분기 → 휴리스틱으로 결정론적 응답.
- **분석 파이프라인**(`app/analysis/pipeline.py`): 재STT → 신호지표 → 필러 → 어휘(MATTR/문장길이) → LLM-judge ×3 → 재작성 → DB + `data/results/{id}.json`.
- **judge**(H1): temperature **0.4**(≠0)로 3회 호출, 차원별 mean+stdev. 0으로 두면 분산이 무의미해진다.

### PoC 환경상의 의도적 결정 (Windows / Python 3.13 / uv 없음)

- **VAD**: `webrtcvad`는 Windows에서 MSVC 컴파일이 필요해 설치가 불안정 → `compute_silence_ratio`는 **순수 numpy 에너지 기반 VAD**로 구현(결정론적). `webrtcvad`가 설치돼 있으면 자동으로 그쪽 사용.
- **F0**: 기본은 **numpy FFT 자기상관** 추정(경량·결정론). `librosa`가 있으면 `compute_f0_stats(method="pyin")`로 `librosa.pyin` 사용 가능(그래서 librosa는 선택적 의존성).
- **형태소**: `kiwipiepy`로 MATTR 계산, 없으면 공백 토큰화로 폴백 → 모킹 테스트는 항상 통과.
- **의존성**: `uv` 미설치라 `requirements.txt`(+ `pyproject.toml`)로 `pip install`. 핵심군만으로 pytest 통과, `anthropic`/`openai`는 실 API용(지연 import).

## 디렉터리

```
app/            config·db·models·schemas·situations
  conversation/ stt·llm·tts(각 Protocol+Real+Mock)·orchestrator·types
  analysis/     signal_metrics·fillers·judge·rewrite·transcript·compare·pipeline
  routes/       sessions·analysis·content
content/situations/  상황 YAML 5개
scripts/        synth_data·demo_run·eval_judge_variance·eval_retake_diff
tests/          test_fillers·test_signal_metrics·test_pipeline
data/           audio/(합성 WAV)·results/(분석 JSON)
```

## 비범위 (§11)

인증/회원가입/JWT, 멀티테넌트, WebSocket 스트리밍, 프론트엔드, Docker/K8s, Alembic, F8 발음·딕션 분석, 로깅/모니터링 — PoC에서 구현하지 않는다.
