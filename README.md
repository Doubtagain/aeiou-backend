# AEIOU PoC (구 VoiceUp)

한국어 **실전 말하기 코치 AEIOU**의 가설 검증용 PoC 백엔드. 사용자가 정서 상황(이별·사과·고백·갈등·거절)과 면접·발표 시나리오를 골라 AI와 음성 대화를 한 뒤, **표현 흐름·즉흥 대응·전달력**과 **답변 길이·반복어·발음**에 대한 코칭 리포트를 받는다.

> 이 코드의 목적은 "보이는 것"을 만드는 게 아니라 **가설(H1~H6)을 검증**하는 것이다.

## v3 변경 요약

- VoiceUp → AEIOU 리브랜딩 ("일상 대화 코칭" → "실전 말하기 코치")
- 상황 카탈로그에 **면접 / 발표 카테고리** 추가 (`category`, `difficulty` 필드)
- **답변 길이 metric**: 음절·어절·초 + 카테고리별 임계값(`too_long_turn_count`)
- **반복어 metric** (필러와 분리): 사용자 고유 n-gram 빈도
- **표준 코칭 카드** 3종 (규칙 기반, LLM 비사용): 핵심부터 / 길이 축소 / 끝음 명확
- **발음 분석** 기본 활성화 (텍스트 가이드 only; Azure PA 실 연동은 v3.1)
- **사용자 맞춤 상황 생성** (프리미엄 게이트: `X-Premium: true` 또는 `ENABLE_PREMIUM=1`)

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

> **v3 스키마 변경 후 DB 재생성** (Alembic 없이 `create_all` 환경):
> `rm aeiou.db && python -c "from app.db import init_db; init_db()"`

## 테스트

```bash
pytest        # 외부 API 호출 없이 모킹으로 통과 (현재 35 passed)
```

## 가설별 검증 방법

| 가설 | 검증 명령 | 합격 기준 |
|---|---|---|
| **H1.** LLM-judge가 일관된 점수를 낸다 | `python scripts/eval_judge_variance.py --runs 5` | 각 평가 차원 표준편차 **≤ 0.7** (5점 척도) |
| **H2.** 필러·운율·페이싱 지표가 합리적이다 | `python scripts/demo_run.py` 후 `data/results/*.json` 검토 | SPM **200~500**, F0 **80~300Hz**, silence_ratio **0.1~0.4** |
| **H3.** 개선 문장이 원의도 유지+목표 부합 | `GET /sessions/{id}/rewrites` 결과 정성 평가 (아래 표) | (정성) 원의도 유지하며 목표에 더 부합 |
| **H4.** 리테이크 비교가 의미 있는 차이를 잡는다 | `python scripts/eval_retake_diff.py` | `better_side == "retake"` 이고 verdict에 "개선" 포함 |
| **H5.** 표준 코칭 카드가 bad 세션에서 합리적으로 트리거된다 | `python scripts/eval_coaching_tips.py` | bad emotional → `clear_ending` 또는 `lead_with_conclusion` / bad interview → `shorten_answer` 또는 `lead_with_conclusion` |
| **H6.** 사용자 맞춤 상황 생성이 사용 가능한 YAML을 만든다 | `python scripts/eval_custom_situation.py` | 3개 자연어 설명 모두 (a) 필수 필드 충족 + (b) opening_line으로 1턴 대화 실행 |

각 모듈은 가설 하나에 대응한다:
`analysis/judge.py`→H1, `analysis/signal_metrics.py`+`fillers.py`+`repetition.py`→H2, `analysis/rewrite.py`→H3, `analysis/compare.py`→H4, `analysis/coaching_tips.py`→H5, `content/generator.py`→H6.

## 합격 기준 (성공 정의)

1. `pytest`가 **실 API 호출 없이** 통과 → ✅ **충족** (35 passed, 전부 Mock)
2. `python scripts/demo_run.py`가 **실 API로** 끝까지 돌아 분석 JSON·비교 verdict 출력 → ⏳ **미실행** (아래 참조)
3. `eval_*.py` 결과가 합격 기준 충족 → ⏳ **실 API 미실행**; mock 모드에서는 H1/H4/H5/H6 모두 PASS

## 검증 결과

### ✅ 자동화 테스트 (실 API 0회)

```
$ pytest
35 passed
```
- `test_fillers` — 사전 매칭 + 다의어 처리 (의미로 쓰인 "그"는 필러로 분류되지 않음)
- `test_signal_metrics` — 1초 사인파(150Hz)에서 F0≈150, SPM/침묵/끝음/지연 + 답변 길이 통계·임계값 분해
- `test_repetition` — 3회 반복 n-gram 검출, 필러-only n-gram 제외, 빈 입력 안전
- `test_coaching_tips` — 트리거 AND/OR, None 안전, 3종 동시 발화
- `test_pronunciation` — weak_words 결정론 mock, AI-only 빈 결과, 중복 제거
- `test_custom_situation` — generator 정상 + premium 게이트 402 + X-Premium 통과 + ENABLE_PREMIUM env
- `test_pipeline` — MockSTT/MockLLM/MockTTS로 분석 파이프라인 전 구간 통과, good ≥ bad 방향성

### ⏳ 실 API 검증 — 이 환경에서는 미실행 (정직한 현황)

`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`가 설정돼 있다면 아래로 실 API 검증을 수행할 수 있다.

```bash
python scripts/demo_run.py
python scripts/eval_judge_variance.py --runs 3
python scripts/eval_retake_diff.py
python scripts/eval_coaching_tips.py
python scripts/eval_custom_situation.py
```

**모킹 모드 스모크 (배관 검증)**

| 항목 | `--mock` 관측값 | 비고 |
|---|---|---|
| demo_run better_side | `retake` (=다듬은 good) | 비교 로직 정상 |
| bad 세션 filler_count / density | 11 / 0.275 | 필러 검출 정상 |
| bad 세션 SPM | ~405 (H2 범위 내) | 텍스트 길이 비례 무음 오디오 기준 |
| 응답 latency p50 | ~611ms | 합성 타임라인 기준 |
| eval_judge_variance | 모든 차원 stdev=0 → PASS | Mock은 결정론적이라 분산 0. 실제 H1은 실 API에서만 의미 |
| eval_retake_diff | better=retake, "개선" 포함 → PASS | good>bad 방향성 |
| eval_coaching_tips (H5) | emotional `clear_ending` / interview `clear_ending`+`lead_with_conclusion` → PASS | bad mock dialogue가 카테고리별로 다름 |
| eval_custom_situation (H6) | 3/3 PASS | 필수 필드 + 1턴 대화 |

> **F0/silence/tail_clarity는 모킹(무음 WAV)에서 의미가 없다** (각각 0/1.0/0). H2의 운율 지표는 **실 TTS 오디오**로 `demo_run.py`를 돌려야 검증된다. SPM·필러·지연·MATTR·답변 길이·반복어·코칭 카드 트리거는 모킹에서도 유효하다.

### H3 재작성 예시 (`--mock` 산출, 정성 평가용 양식)

| 원본(사용자) | 재작성 v1 | 재작성 v2 |
|---|---|---|
| "음 그냥 뭐 잘 모르겠어" | "잘 모르겠어" (군말 제거) | "솔직히 말하면, 잘 모르겠어" (감정 노출 강화) |

실제 품질은 실 Claude로 `GET /sessions/{id}/rewrites`를 호출해 평가할 것. (Mock은 군말 제거 + 정형 변형만 수행)

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/situations?category=&author=` | 상황 카탈로그 (v3: category·author 필터) |
| POST | `/situations/custom` | **v3·프리미엄**: 자유 텍스트 → 맞춤 SituationConfig (`X-Premium: true` 또는 `ENABLE_PREMIUM=1`) |
| POST | `/sessions` | 세션 생성 → `{session_id, opening_audio_url, opening_text}` |
| POST | `/sessions/{id}/turn` | multipart(audio+turn_index) → `{ai_text, ai_audio_url, transcript}` |
| POST | `/sessions/{id}/end` | 분석을 백그라운드 시작 → `{analysis_job_id}` |
| GET | `/sessions/{id}/analysis` | `SessionAnalysis` 또는 `{status:"pending"}` (v3: 답변 길이·반복어 컬럼 포함) |
| GET | `/sessions/{id}/rewrites` | `[RecommendedRewrite]` (하위 호환) |
| GET | `/sessions/{id}/coaching` | **v3**: `{tips: [규칙 기반 카드], rewrites: [LLM 재작성]}` |
| GET | `/sessions/{id}/pronunciation` | **v3**: `{weak_words: [...]}` (텍스트 가이드 only) |
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
  analysis/     signal_metrics·fillers·repetition·judge·rewrite·coaching_tips·pronunciation·transcript·compare·pipeline
  content/      generator (v3 사용자 맞춤 상황)
  routes/       sessions·analysis·content
content/situations/  상황 YAML 7개 (emotional 5 + interview/presentation)
scripts/        synth_data·demo_run·eval_judge_variance·eval_retake_diff·eval_coaching_tips·eval_custom_situation
tests/          test_fillers·test_signal_metrics·test_pipeline·test_repetition·test_coaching_tips·test_pronunciation·test_custom_situation
data/           audio/(합성 WAV)·results/(분석 JSON)
```

## 비범위 (v3)

- Azure Pronunciation Assessment 실 연동 → v3.1
- 조음점 시각화 애니메이션 (Rive/Lottie) → 프로덕션 단계
- 결제 모듈 (현재는 `X-Premium` 헤더 / 환경변수 게이트)
- WebSocket 실시간 대화 (POST 턴 유지)
- 사용자 맞춤 상황의 안전성 필터 → v3.2
- 인증/회원가입/JWT, 멀티테넌트, 프론트엔드, Docker/K8s, Alembic, 로깅/모니터링 — PoC 비범위 유지
