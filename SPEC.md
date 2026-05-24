# Claude Code 프롬프트 — VoiceUp PoC 백엔드 구현 지시서

> 이 문서를 Claude Code의 첫 메시지로 통째로 붙여넣거나, 프로젝트 루트에 `SPEC.md`로 저장한 뒤 "Read SPEC.md and implement it"로 시작하면 됩니다.

---

## 0. 메타 지시 (Claude Code에게)

당신은 VoiceUp이라는 한국어 대화 코칭 서비스의 **PoC 백엔드**를 만든다.
목표는 프로덕션 코드가 아니라 **가설 검증용 최소 구현체**다. 다음 원칙을 지켜라.

- **단순 우선**: 인증/멀티유저/배포 설정 없음. 로컬 실행 + 단일 사용자.
- **외부 서비스는 모킹 가능하게**: 모든 외부 API 호출은 어댑터 계층 뒤로 숨기고, `--mock` 플래그로 결정론적 모킹이 가능해야 한다.
- **합성 데이터 자체 생성**: Claude가 한국어 대화 스크립트를 생성 → OpenAI TTS로 음성 파일 렌더링 → 분석 파이프라인 입력으로 사용. 실제 사람 녹음 없이도 전 구간이 굴러가야 한다.
- **검증 가능성이 최우선**: 모든 분석 결과는 JSON으로 저장되어, 동일 입력에 대한 LLM-judge 결과 분산을 측정할 수 있어야 한다.
- **언어**: Python 3.11+, FastAPI, uvicorn, Pydantic v2. 의존성은 `pyproject.toml`(uv) 또는 `requirements.txt`로 명시.
- **테스트**: pytest 기본 셋업. 핵심 유닛 3~5개만.

작업이 끝나면 README에 "어떤 가설이 어떤 명령으로 검증되는가"를 명시하라.

---

## 1. 프로젝트 배경 (간략)

VoiceUp은 사용자가 일상 상황(이별, 사과, 고백, 갈등 등)을 골라 AI와 2~3분 음성 대화를 한 뒤, 표현 흐름·즉흥 대응·전달력에 대한 코칭 리포트를 받는 서비스다. PoC에서 검증하려는 가설:

| 가설 | 검증 방법 |
|---|---|
| H1. 한국어 자유 대화에 대해 LLM-as-judge가 일관된 점수를 낸다 | 같은 입력으로 LLM-judge 3회 실행, 분산이 임계치 이하인지 확인 |
| H2. 필러·운율·페이싱 정량 지표가 합리적인 값으로 산출된다 | 합성 샘플 5개에 대해 SPM/필러수/F0 등이 사람이 보기에 납득되는 범위인지 확인 |
| H3. "개선 문장 추천"이 원본 의도를 유지하면서 목표에 더 부합한다 | 5개 발화 × 2가지 목표로 재작성 결과를 사람이 정성 평가 |
| H4. 리테이크 비교가 의미 있는 차이를 잡아낸다 | "의도적으로 망친 버전"과 "다듬은 버전"을 두 세션으로 넣고 LLM-judge가 후자를 더 높게 평가하는지 확인 |

PoC 코드의 각 모듈은 위 가설 중 하나에 직접 대응하도록 짜라.

---

## 2. 기술 스택 (확정)

| 영역 | 선택 |
|---|---|
| 언어/프레임워크 | Python 3.11, FastAPI, uvicorn, Pydantic v2 |
| 의존성 관리 | uv (또는 pip + requirements.txt) |
| LLM | **Anthropic Claude Sonnet 4.6** (`claude-sonnet-4-6`) — 대화·평가·재작성 모두 |
| STT | **OpenAI Whisper API** (`whisper-1`) — 한국어 지원, 단어 타임스탬프 필요시 `verbose_json` 응답 + word_timestamps |
| TTS | **OpenAI gpt-4o-mini-tts** — 합성 샘플 + AI 응답 음성. 한국어 발화 지원 |
| 신호 처리 | librosa, numpy, scipy, webrtcvad (또는 silero-vad) |
| 한국어 형태소 | kiwipiepy (`pip install kiwipiepy` — Mecab보다 설치 쉬움) |
| DB | SQLite + SQLAlchemy 2.x (PoC 단계, Postgres 호환 스키마 유지) |
| 잡 큐 | 단순 in-process `asyncio.create_task` 또는 FastAPI BackgroundTasks (Celery 금지, 너무 무거움) |
| 테스트 | pytest, httpx (TestClient) |

환경변수: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. `.env.example` 파일 작성.

---

## 3. 디렉터리 구조

```
voiceup-poc/
├── pyproject.toml              # 의존성
├── README.md                   # 실행/검증 방법
├── SPEC.md                     # 이 문서 사본
├── .env.example
├── app/
│   ├── main.py                 # FastAPI 앱 엔트리
│   ├── config.py               # 환경변수 로딩
│   ├── db.py                   # SQLAlchemy 엔진/세션
│   ├── models.py               # ORM 모델 (5.1 참조)
│   ├── schemas.py              # Pydantic 스키마
│   ├── routes/
│   │   ├── sessions.py         # /sessions, /sessions/{id}/end, /retake
│   │   ├── analysis.py         # /sessions/{id}/analysis
│   │   └── content.py          # /situations
│   ├── conversation/
│   │   ├── orchestrator.py     # 대화 턴 진행
│   │   ├── stt.py              # Whisper 어댑터 (+ mock)
│   │   ├── llm.py              # Claude 어댑터 (+ mock)
│   │   └── tts.py              # OpenAI TTS 어댑터 (+ mock)
│   └── analysis/
│       ├── pipeline.py         # 잡 오케스트레이션
│       ├── transcript.py       # verbatim STT 재처리
│       ├── signal_metrics.py   # SPM, F0, 에너지, 침묵
│       ├── fillers.py          # 한국어 필러 검출 (사전 + LLM)
│       ├── judge.py            # LLM-as-judge 프롬프트 + 3회 반복
│       ├── rewrite.py          # 개선 문장 생성
│       └── compare.py          # 리테이크 비교
├── content/
│   └── situations/             # YAML 상황 정의 (5개)
│       ├── breakup_last_conversation.yaml
│       ├── apology_after_mistake.yaml
│       ├── confession_to_friend.yaml
│       ├── conflict_with_colleague.yaml
│       └── refusing_a_request.yaml
├── scripts/
│   ├── synth_data.py           # 합성 세션 생성 (5.4 참조)
│   ├── eval_judge_variance.py  # H1 검증
│   ├── eval_retake_diff.py     # H4 검증
│   └── demo_run.py             # 전체 플로우 1회 시연
├── data/
│   ├── audio/                  # 합성 WAV 저장
│   └── results/                # 분석 결과 JSON
└── tests/
    ├── test_fillers.py
    ├── test_signal_metrics.py
    └── test_pipeline.py
```

---

## 4. 외부 어댑터 인터페이스

각 어댑터는 **인터페이스 + 실 구현 + Mock 구현** 3개로 구성한다. `--mock` 옵션이나 환경변수 `USE_MOCKS=1`이면 Mock으로 스위치.

```python
# app/conversation/stt.py
class STT(Protocol):
    async def transcribe(self, audio_path: Path, *, verbatim: bool = False) -> Transcript: ...

class WhisperSTT(STT): ...
class MockSTT(STT):
    """audio_path와 같은 폴더의 *.transcript.json을 읽어 반환."""

# app/conversation/llm.py
class LLM(Protocol):
    async def chat(self, system: str, messages: list[Message]) -> str: ...
    async def chat_json(self, system: str, user: str, schema: dict) -> dict: ...

class ClaudeLLM(LLM): ...   # claude-sonnet-4-6
class MockLLM(LLM):
    """프롬프트 hash → 사전 정의된 응답 매핑."""

# app/conversation/tts.py
class TTS(Protocol):
    async def synthesize(self, text: str, voice: str, out_path: Path) -> None: ...

class OpenAITTS(TTS): ...   # gpt-4o-mini-tts
class MockTTS(TTS):
    """무음 WAV 생성 (길이는 text 길이에 비례)."""
```

**Mock 구현은 결정론적**이어야 한다 (CI/테스트에서 외부 호출 없이도 통과). 단, 가설 검증 스크립트(`eval_*.py`)는 실 API를 호출하는 모드로 돌릴 것.

---

## 5. 구체적 구현 요구사항

### 5.1 데이터 모델

SQLite 기준이지만 Postgres 호환 스키마. v2 문서의 모델을 그대로 따르되 PoC에서 필요한 것만 남긴다.

```python
class User(Base): id, email, created_at
class Situation(Base): id (TEXT), title, yaml_path, active
class Session(Base):
    id, user_id, situation_id, goal_id,
    parent_session_id (Nullable, 리테이크용),
    started_at, ended_at, duration_sec
class Turn(Base):
    id, session_id, turn_index, speaker ('user'|'ai'),
    audio_path, start_ts_ms, end_ts_ms,
    transcript, transcript_verbatim
class SessionAnalysis(Base):
    session_id (PK, FK),
    # 표현 흐름
    flow_coherence: float, flow_consistency: float,
    flow_goal_alignment: float, flow_avoidance: float,
    vocab_mattr: float, sentence_length_stdev: float,
    # 즉흥 대응
    latency_p50_ms: float, latency_p90_ms: float,
    filler_count: int, filler_density: float,
    topic_adherence: float, recovery_score: float,
    # 전달력
    spm_mean: float, spm_stdev: float,
    f0_mean: float, f0_stdev: float,
    silence_ratio: float, tail_clarity: float,
    # 메타
    judge_runs: JSON,   # 3회 반복 원본
    judge_variance: JSON,
    raw_payload: JSON,
    created_at
class RecommendedRewrite(Base):
    id, session_id, source_turn_id,
    original_text, rewrites (JSON)
class RetakeComparison(Base):
    id, baseline_session_id, retake_session_id,
    better_side ('baseline'|'retake'|'tie'),
    diff_summary (JSON), llm_verdict (TEXT)
```

`Alembic` 없이 `Base.metadata.create_all`로 초기화. PoC.

### 5.2 상황 YAML 5개

`content/situations/` 아래에 v2 문서의 형식대로 5개를 미리 작성하라. 각 YAML은 다음 키 필수:

```yaml
id: <snake_case>
title: <한국어 상황 제목>
ai_persona: |
  <시스템 프롬프트, 6~10줄>
opening_line: <AI 첫 발화>
duration_target_sec: [120, 180]
goal_options:
  - id: <goal_id>
    label: <한국어 라벨>
    eval_focus: [<평가 포커스 키워드 2~4개>]
target_phonemes: []   # PoC에서는 빈 배열 (F8 부가기능 미구현)
```

5개는: 이별 마지막 대화, 실수 후 사과, 친구에게 고백, 동료와의 갈등, 부탁 거절. 각 2~3개 goal_options.

### 5.3 핵심 분석 모듈

#### `analysis/signal_metrics.py`

```python
def compute_spm(turns: list[Turn]) -> tuple[float, float]:
    """음절 수 / (발화 시간 분) 의 평균과 표준편차"""
    # Hangul 음절 카운트는 [가-힣] 정규식 매칭

def compute_f0_stats(audio_path: Path) -> dict:
    """librosa.pyin 또는 parselmouth로 F0 평균/표준편차/범위.
    무음 구간 제외. 30~400Hz 범위로 클리핑."""

def compute_silence_ratio(audio_path: Path, vad: Vad) -> float:
    """webrtcvad 또는 silero-vad로 무음/전체 비율"""

def compute_tail_clarity(audio_path: Path, tail_ms: int = 300) -> float:
    """발화 마지막 tail_ms 구간의 RMS 에너지 / 전체 발화 평균 RMS 비율.
    낮을수록 끝음이 흐려진 것."""

def compute_response_latencies(turns: list[Turn]) -> dict:
    """AI 종료 → 사용자 시작 시각 차이의 p50/p90"""
```

#### `analysis/fillers.py`

```python
FILLER_DICT = {"음", "어", "그", "뭐", "약간", "좀", "그냥", "있잖아", "아니", "막"}

def candidate_fillers(transcript_verbatim: str, words: list[Word]) -> list[FillerCandidate]:
    """1차: 사전 매칭. 단, 다의어("그", "좀", "막")는 무조건 후보로만"""

async def classify_fillers(candidates: list[FillerCandidate], llm: LLM) -> list[Filler]:
    """2차: Claude에게 문맥 ±5단어를 보여주고 진짜 필러인지 분류.
    가능하면 한 번의 호출로 모든 후보를 배치 처리."""
```

#### `analysis/judge.py`

```python
JUDGE_PROMPT_FLOW = """..."""    # v2 문서 §6.2 참조, 한국어 프롬프트
JUDGE_PROMPT_IMPROV = """..."""

async def judge_flow(session: Session, llm: LLM, n_runs: int = 3) -> JudgeResult:
    """n_runs회 호출, 점수 평균과 표준편차 모두 반환.
    JSON 모드(또는 tool use)로 강제 구조화."""

async def judge_improv(session: Session, llm: LLM, n_runs: int = 3) -> JudgeResult: ...

def judge_variance_report(runs: list[dict]) -> dict:
    """각 차원의 표준편차를 계산해 H1 검증용 메트릭 반환"""
```

**중요**: LLM 호출 시 `temperature`를 0이 아닌 0.3~0.5로 두라. 0으로 두면 분산이 0에 가까워 H1 검증이 무의미해진다. 또한 같은 모델로 평가와 대화를 둘 다 돌려도 무방하지만, 평가 호출에는 system 메시지에 "당신은 한국어 대화 코치이며, 평가 기준에 엄격하게 따른다"를 강조하라.

#### `analysis/rewrite.py`

```python
async def recommend_rewrites(
    session: Session, analysis: SessionAnalysis, llm: LLM
) -> list[RecommendedRewrite]:
    """1) analysis 점수에서 약점 차원 식별
       2) 해당 차원에 영향이 큰 turn 3~5개 선정 (간단히는 가장 긴 사용자 발화)
       3) 각 발화에 대해 2~3가지 버전 재작성
       4) 각 버전에 rationale 포함"""
```

#### `analysis/compare.py`

```python
async def compare_sessions(
    baseline: Session, retake: Session, llm: LLM
) -> RetakeComparison:
    """v2 문서 §10.2 프롬프트를 사용.
    정량 차이(SPM, filler, latency)는 코드로 계산해 LLM에 입력으로 넣는다."""
```

### 5.4 합성 데이터 생성 (`scripts/synth_data.py`)

가장 중요한 스크립트. 다음 두 모드를 지원하라.

```
python scripts/synth_data.py --situation breakup_last_conversation \
                              --goal clear_closure \
                              --quality good \
                              --out data/audio/session_001
```

- `--quality`: `good`(다듬은 발화) | `bad`(필러 많고 회피 많은 발화) | `mixed`(혼합)
- 동작:
  1. Claude에게 상황 YAML과 quality 옵션을 보여주고 8~20턴 대화 스크립트 생성 요청
  2. AI 턴은 OpenAI TTS 한국어 음성 1(예: `nova` 또는 `alloy`)으로, 사용자 턴은 음성 2(예: `echo`)로 합성
  3. 각 턴 WAV를 `data/audio/session_xxx/turn_{i:02d}_{speaker}.wav`로 저장
  4. 메타데이터 `data/audio/session_xxx/session.json`에 턴별 텍스트와 타임라인 기록
  5. DB에 Session + Turn 레코드 삽입

`bad` 모드 프롬프트에는 명시적으로 "필러 단어(음/어/그/막)를 자주 섞고, 직접적인 답을 회피하며 둘러말하는 식으로 작성하라"를 포함시켜라. 검증 신호가 분명해진다.

### 5.5 분석 파이프라인 (`analysis/pipeline.py`)

```python
async def run_analysis(session_id: UUID) -> SessionAnalysis:
    # 1. 세션 + 턴 로딩
    # 2. 사용자 턴 오디오를 합쳐 verbatim STT 재처리 (Whisper) → turn별 word timestamps
    # 3. signal_metrics: SPM, F0, silence, tail_clarity, latencies
    # 4. fillers: 후보 추출 → 배치 LLM 분류 → 최종 카운트
    # 5. vocab/structure: kiwipiepy로 형태소 분석 → MATTR, sentence length stdev
    # 6. judge_flow / judge_improv 각 3회 실행
    # 7. recommend_rewrites
    # 8. DB 저장 + JSON dump to data/results/{session_id}.json
```

세션 종료 후 호출되며 백그라운드로 돌아간다. 클라이언트는 `GET /sessions/{id}/analysis`로 poll 가능.

---

## 6. API 엔드포인트 (FastAPI)

```
POST   /sessions                          { situation_id, goal_id } → { session_id, opening_audio_url, opening_text }
POST   /sessions/{id}/turn                multipart: audio + turn_index
                                          → { ai_text, ai_audio_url, transcript }   # 실시간 대화 1턴
POST   /sessions/{id}/end                 → { analysis_job_id }
GET    /sessions/{id}/analysis            → SessionAnalysis | { status: "pending" }
GET    /sessions/{id}/rewrites            → [RecommendedRewrite]
POST   /sessions/{id}/retake              { mode: "situation" } → { new_session_id }
GET    /comparisons/{retake_session_id}   → RetakeComparison
GET    /situations                        → 카탈로그
```

오디오 응답은 파일로 저장 후 정적 서빙(`/static/audio/...`)으로 충분. PoC에서 WebSocket 스트리밍은 생략, **POST /turn**으로 턴 단위 처리.

---

## 7. 검증 스크립트

### 7.1 `scripts/demo_run.py` — 전체 플로우 1회

```
python scripts/demo_run.py
```

- `--mock` 없이 실 API 사용
- 절차: 합성 good 세션 1개 생성 → 분석 실행 → 결과 출력 → 합성 bad 세션 1개 생성 → 분석 → 비교(`compare_sessions`) → 결과 출력
- 콘솔 출력에 모든 핵심 지표 + better_side 표시

### 7.2 `scripts/eval_judge_variance.py` — H1 검증

```
python scripts/eval_judge_variance.py --runs 5
```

- 합성 세션 1개 분석을 5회 반복(매 회마다 judge 3중 내부 반복도 새로 호출)
- 각 차원(coherence, consistency, goal_alignment, ...)별 점수 표준편차 출력
- **합격 기준**: 각 차원 표준편차 ≤ 0.7 (5점 척도 기준)

### 7.3 `scripts/eval_retake_diff.py` — H4 검증

```
python scripts/eval_retake_diff.py
```

- 같은 상황·같은 목표로 bad 세션과 good 세션 각각 합성
- bad → baseline, good → retake로 비교 호출
- **합격 기준**: better_side == "retake" 그리고 LLM verdict에 "개선"이라는 단어 포함

각 스크립트는 결과를 `data/results/eval_*.json`으로 저장.

---

## 8. 테스트 (pytest)

최소 3개:

- `tests/test_fillers.py`: 사전 매칭 케이스 + 다의어 케이스 (의미 사용된 "그" 가 필러로 분류되지 않는지)
- `tests/test_signal_metrics.py`: 1초짜리 합성 사인파 WAV로 SPM/F0가 합리적 범위인지
- `tests/test_pipeline.py`: MockSTT/MockLLM/MockTTS로 분석 파이프라인이 끝까지 돌아가는지 (실 API 호출 없이)

`pytest`만 치면 모든 게 모킹된 채로 5초 안에 통과해야 한다.

---

## 9. README 요구사항

다음 섹션을 포함하라.

```
# VoiceUp PoC

## 빠른 시작
1. .env 작성 (ANTHROPIC_API_KEY, OPENAI_API_KEY)
2. uv sync (또는 pip install -r requirements.txt)
3. python scripts/synth_data.py --situation breakup_last_conversation --goal clear_closure --quality good --out data/audio/demo
4. uvicorn app.main:app --reload
5. python scripts/demo_run.py

## 가설별 검증 방법
- H1 (LLM-judge 일관성): python scripts/eval_judge_variance.py --runs 5
- H2 (정량 지표 합리성): python scripts/demo_run.py 결과의 data/results/*.json 수동 검토
- H3 (재작성 품질): /sessions/{id}/rewrites 결과를 README 표로 정리
- H4 (리테이크 차이): python scripts/eval_retake_diff.py

## 합격 기준
- H1: 각 평가 차원 표준편차 ≤ 0.7
- H2: SPM 200~500, F0 80~300Hz, silence_ratio 0.1~0.4 범위
- H4: better_side == "retake"
```

---

## 10. 구현 순서 (Claude Code 권장)

다음 순서로 진행하라. 각 단계 끝나면 git commit.

1. 디렉터리 + pyproject.toml + .env.example + README 뼈대
2. DB 모델 + 5개 상황 YAML
3. 어댑터 인터페이스 + Mock 구현 (실 API 없이도 import 통과)
4. `signal_metrics.py` + `fillers.py` 구현 + 유닛 테스트
5. `judge.py` + `rewrite.py` 구현 (실 Claude 호출 포함)
6. `pipeline.py` 통합
7. FastAPI 라우트
8. 실 어댑터(Whisper, Claude, OpenAI TTS) 구현
9. `synth_data.py`
10. `demo_run.py`, `eval_*.py` 검증 스크립트
11. README의 가설 검증 표 채우기

---

## 11. 비범위 (NOT to build)

다음은 PoC에서 **구현하지 않는다**. 시간을 쓰지 마라.

- 사용자 인증/회원가입/JWT
- 멀티 테넌트, 권한 관리
- WebSocket 실시간 스트리밍 (POST 턴으로 갈음)
- 모바일 클라이언트 / 프론트엔드 일체
- Docker / Kubernetes / 배포 스크립트
- Alembic 마이그레이션 (create_all로 OK)
- F8 발음·딕션 분석 (v2의 부가 기능, 추후)
- 가이드 애니메이션 (v1 잔재, 폐기)
- 로깅/모니터링/메트릭 수집 (print + JSON dump면 충분)

---

## 12. 성공 정의

다음 3개가 모두 충족되면 PoC 성공.

1. `pytest` 통과 (실 API 호출 없이 5초 이내)
2. `python scripts/demo_run.py`가 실 API로 끝까지 돌아 분석 JSON과 비교 verdict를 출력
3. `eval_judge_variance.py`의 분산 결과와 `eval_retake_diff.py`의 verdict가 README의 합격 기준을 만족

위 3개가 안 나오면 어디서 실패했는지 README에 솔직히 적어라. "보이는 것을 만든" 것이 아니라 **가설을 검증한 것**이 PoC의 목적이다.

---

## 부록: Claude Sonnet 4.6 호출 예시 스니펫

```python
# app/conversation/llm.py
from anthropic import AsyncAnthropic

class ClaudeLLM:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        # JSON 강제: tool use 또는 명시적 프롬프트 + 파싱
        msg = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=0.4,           # judge용은 0.3~0.5
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = msg.content[0].text
        return _extract_json_block(text)
```

호출은 모두 `async`로. FastAPI 라우트도 `async def`.

---

이 스펙대로 만들면 약 1,500~2,500 LOC 규모의 PoC가 나온다. Claude Code가 단일 세션에서 끝까지 완수 가능한 크기다. 시작하라.
