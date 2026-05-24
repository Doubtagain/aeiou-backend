# Claude Code 마이그레이션 프롬프트 — VoiceUp PoC → AEIOU v3

> 이전 SPEC.md(VoiceUp PoC)를 기반으로 이미 구현된 코드베이스를 **AEIOU v3 스펙**으로 업데이트한다.
> 이 문서를 `MIGRATION.md`로 저장하고, Claude Code에서 "MIGRATION.md를 읽고 §3 변경 작업을 순서대로 진행해줘"로 시작.

---

## 0. 메타 지시

- 새 코드를 작성하기 전에 **먼저 기존 SPEC.md / README / 코드 구조를 빠르게 스캔**해 어디까지 구현되어 있는지 확인하라.
- 변경 단위마다 별도 commit. 메시지는 `feat(v3): ...`, `refactor(v3): ...` 형태.
- 기존에 통과하던 `pytest`와 `scripts/demo_run.py`가 v3 변경 후에도 계속 동작해야 한다. 깨지면 즉시 고친다.
- 새 의존성 추가는 최소화. 가능하면 기존 모듈에 함수 추가.

---

## 1. 변경 배경 (요약만)

서비스가 다음과 같이 재정의되었다.

- **제품명**: VoiceUp → **AEIOU**
- **포지셔닝**: "일상 대화 코칭" → **"실전 말하기 코치"**. 정서 상황 + 면접·발표까지 폭이 넓어졌다.
- **분석 축 재정렬**: 표현 흐름 / 즉흥 대응 / 전달력의 큰 틀은 유지하되, **답변 길이**와 **반복어**가 신규 측정 차원으로 추가됨.
- **개선 포인트 템플릿화**: 자유 재작성 외에 **3가지 표준 코칭 카드**(핵심부터/길이 축소/끝음 명확)도 함께 노출.
- **발음 분석 복귀**: "부가 기능"이 아니라 **"차별 기능"**으로 격상. 단 PoC에서는 텍스트 가이드만(애니메이션 없음).
- **사용자 맞춤 상황 생성**: 프리미엄 기능 후보로, 사용자가 자유 텍스트로 상황을 묘사하면 AI가 시나리오 YAML을 생성.

---

## 2. 변경 영향 매트릭스

| 영역 | 변경 유형 | 위치 |
|---|---|---|
| 제품명 리브랜딩 | 문자열 치환 | README, SPEC, 주석, 합성 데이터 등 전반 |
| 상황 카탈로그 확장 | 신규 YAML 2개 + 카테고리 필드 | `content/situations/` |
| 답변 길이 metric | 신규 함수 + DB 컬럼 + 분석 파이프라인 호출 | `analysis/signal_metrics.py`, `models.py`, `pipeline.py` |
| 반복어 metric | 신규 모듈 (필러와 분리) | `analysis/repetition.py` (신규) |
| 표준 코칭 카드 | 신규 규칙 기반 추천기 | `analysis/coaching_tips.py` (신규) |
| 발음 분석 활성화 | 기존 F8 부가 → 항상 실행 (사용자 토글 제거) | `analysis/pronunciation.py`, `pipeline.py` |
| 사용자 맞춤 상황 | 신규 라우트 + LLM 호출 | `routes/content.py`, `app/content/generator.py` |
| 새 가설 추가 | H5, H6 검증 스크립트 | `scripts/eval_*.py` |

---

## 3. 작업 순서 (Claude Code는 이대로 진행)

### Step 1 — 리브랜딩 (5분)

- 프로젝트명을 모든 곳에서 **AEIOU**로 변경:
  - `pyproject.toml`의 `name = "voiceup-poc"` → `name = "aeiou-poc"`
  - README 제목, FastAPI `app = FastAPI(title="AEIOU PoC")`
  - 디렉터리 `voiceup-poc/`는 그대로 둬도 됨 (Git history 깨짐 방지). README 첫줄에 "구 VoiceUp"이라고만 명기.
- 합성 데이터의 사용자/AI 페르소나 문구에 "VoiceUp"이 포함된 곳이 있으면 교체.

### Step 2 — 상황 카탈로그 확장

기존 5개(이별/사과/고백/갈등/거절) 위에 다음 카테고리 필드를 추가한다.

```yaml
# 모든 situation YAML에 추가
category: emotional   # 또는 interview / presentation / business
difficulty: 2         # 1~3
```

기존 5개는 모두 `category: emotional, difficulty: 1~2`로 매핑.

**신규 YAML 2개**를 `content/situations/`에 작성:

- `interview_behavioral.yaml` (category: interview)
  - `title: "행동 면접 — 협업에서 어려웠던 순간"`
  - `ai_persona`: 실리콘밸리 IT 회사 시니어 면접관, 차분하고 후속 질문이 날카로움
  - `opening_line: "최근에 협업에서 가장 어려웠던 순간을 STAR로 설명해주실 수 있을까요?"`
  - `goal_options`:
    - `structured_star` — "STAR 구조로 답변하기" (eval_focus: 구조 명확성, 결론 우선)
    - `concise_impact` — "결론과 임팩트를 앞에 두기" (eval_focus: 핵심 우선, 길이 절제)
  - `duration_target_sec: [120, 240]`

- `presentation_pitch.yaml` (category: presentation)
  - `title: "신규 기능 사내 피칭"`
  - `ai_persona`: 비기술 팀 임원, 본질만 듣고 싶어함, 5분 안에 끝내야 함
  - `opening_line: "이 기능을 왜 지금 만들어야 하는지, 1분만 먼저 말씀해주세요."`
  - `goal_options`:
    - `clear_problem_first` — "문제→해결→임팩트 순서"
    - `audience_aware` — "비기술 청자 눈높이"

**라우트 변경**: `GET /situations`가 `?category=interview` 같은 필터를 지원하도록.

### Step 3 — 답변 길이 metric

`app/analysis/signal_metrics.py`에 다음 함수 추가:

```python
def compute_answer_lengths(turns: list[Turn]) -> dict:
    """사용자 턴별 답변 길이(음절 수, 단어 수, 초)와 통계 반환.

    Returns:
      {
        "per_turn": [{"turn_index": i, "syllables": ..., "words": ..., "sec": ...}, ...],
        "syllable_mean": float, "syllable_stdev": float,
        "sec_mean": float, "sec_stdev": float,
        "too_long_turns": [turn_index, ...]  # 상황별 기준선 초과
      }
    """
```

기준선(`too_long_turns` 판정):
- `category == interview`: 턴 평균 60초 초과
- `category == presentation`: 턴 평균 90초 초과
- `category == emotional`: 턴 평균 30초 초과

기준선은 `content/situations/*.yaml`에 `answer_length_guideline_sec` 필드로 둘 수 있게 하되, 없으면 위 디폴트.

**DB 컬럼 추가** (`models.py`의 `SessionAnalysis`):

```python
answer_length_syllable_mean: float
answer_length_sec_mean: float
answer_length_sec_stdev: float
too_long_turn_count: int
```

마이그레이션은 SQLite + `create_all` 환경이라 DB 파일을 한 번 지우고 재생성하거나 (`rm aeiou.db && python -c "from app.db import init; init()"`), `ALTER TABLE`을 수동으로 추가. PoC 단계에서는 **DB 재생성**이 빠르다. README에 한 줄 추가.

`analysis/pipeline.py`에서 `compute_answer_lengths`를 호출하고 SessionAnalysis 컬럼에 매핑.

### Step 4 — 반복어 metric (필러와 분리)

신규 모듈 `app/analysis/repetition.py`:

```python
from collections import Counter
from kiwipiepy import Kiwi

KIWI = Kiwi()

def detect_repetitions(transcripts: list[str], min_freq: int = 3, min_len: int = 2) -> dict:
    """반복 표현(2~5어절 n-gram) 중 동일 세션 내 min_freq 이상 등장한 것 반환.

    Returns:
      {
        "repeated_phrases": [{"phrase": "...", "count": int, "turns": [i, ...]}],
        "repetition_ratio": float  # 전체 어절 중 반복 표현이 차지하는 비율
      }
    """
```

**필러와의 구분**:
- 필러는 단일 토큰(`음/어/그/막` 등) 또는 정해진 표현(`있잖아`)
- 반복어는 **사용자 고유 표현이 동일 세션에서 자주 등장**하는 케이스 (예: "그런 거 있잖아요", "그러니까 결국에는")
- 두 모듈은 독립 실행, SessionAnalysis에 별도 컬럼.

`SessionAnalysis`에 `repeated_phrase_count: int`, `repetition_ratio: float`, `raw_payload`에 `repeated_phrases` 리스트.

`tests/test_repetition.py` 추가 — 동일 표현이 3회 등장한 합성 입력에서 검출되는지.

### Step 5 — 표준 코칭 카드 (개선 포인트)

신규 모듈 `app/analysis/coaching_tips.py`:

```python
TIP_TEMPLATES = {
    "lead_with_conclusion": {
        "title": "핵심부터 말해보세요",
        "trigger": lambda a: a.flow_goal_alignment < 3.5 and a.answer_length_sec_mean > 25,
        "body": "답변의 결론이 뒤쪽에 나오면 듣는 사람이 핵심을 놓치기 쉬워요. "
                "첫 문장에 결론을 먼저 두고 이유와 근거를 뒤에 붙여보세요."
    },
    "shorten_answer": {
        "title": "답변 길이를 줄여보세요",
        "trigger": lambda a: a.too_long_turn_count >= 2,
        "body": "한 답변이 길어질수록 전달력이 떨어집니다. 핵심 1~2문장 + 짧은 근거 1개 정도로 정리해보세요."
    },
    "clear_ending": {
        "title": "문장 끝을 더 명확히 말해보세요",
        "trigger": lambda a: a.tail_clarity < 0.6,
        "body": "문장 끝에서 음량이 작아지거나 흐려지면 상대가 되묻기 쉬워요. 마지막 음절까지 호흡을 유지해보세요."
    },
}

def generate_coaching_tips(analysis: SessionAnalysis) -> list[CoachingTip]:
    """규칙 기반으로 활성화된 팁 카드를 반환. 활성 팁이 없으면 빈 리스트."""
```

이건 **LLM이 아닌 규칙 기반**이다. 결정론적이라 디버깅이 쉽고, 사용자가 "왜 이 팁이 나왔는지" 추적 가능.

`analysis/rewrite.py`(자유 재작성)는 그대로 두되, API 응답에서는 두 종류를 같이 노출:

```
GET /sessions/{id}/coaching
→ {
    "tips": [<규칙 기반 카드>],      # 신규
    "rewrites": [<LLM 재작성>]       # 기존 /rewrites와 동일 데이터
  }
```

기존 `/sessions/{id}/rewrites`도 유지(하위 호환).

### Step 6 — 발음 분석 활성화 (차별 기능)

기존 `app/analysis/pronunciation.py`가 토글 뒤에 숨어 있다면 **기본 ON**으로 변경.

PoC에서는 외부 API(Azure Pronunciation Assessment) 통합이 무겁다. 대신 **간이 발음 분석**으로 시작:

```python
async def analyze_pronunciation(turns: list[Turn], llm: LLM) -> dict:
    """1) 사용자 턴의 verbatim transcript를 Claude에게 보여주고
       2) "이 발화에서 발음이 뭉개졌을 가능성이 가장 높은 단어 3개와 그 이유"를 추출
       3) 각 단어에 대해 조음점 가이드 텍스트(예: 'ㅊ → 혀끝을 윗잇몸 근처에...')를 생성
       애니메이션 없이 텍스트만."""
```

이건 ASR 신뢰도(word confidence)를 활용하면 더 정확하지만, Whisper API의 word confidence는 일관성이 부족하므로 PoC에서는 **LLM 추정 + 음성 길이 비교** 정도로 출발.

응답 형식:

```json
{
  "weak_words": [
    {
      "word": "상처",
      "turn_index": 3,
      "phoneme_focus": "ㅊ",
      "articulation_tip": "혀끝을 윗잇몸 근처에 두고, 공기를 짧게 터뜨리듯 발음해보세요."
    }
  ]
}
```

`GET /sessions/{id}/pronunciation` 라우트 신설. 응답 시간이 길어지면 분석 파이프라인의 마지막 단계로 별도 비동기 처리.

후속: Azure PA 실 연동은 v3.1에서 처리. PoC 검증 단계에서는 이 단계까지면 충분.

### Step 7 — 사용자 맞춤 상황 생성

신규 모듈 `app/content/generator.py`:

```python
async def generate_situation(
    user_description: str, category_hint: str | None, llm: LLM
) -> SituationConfig:
    """사용자가 자유 텍스트로 묘사한 상황을 받아 YAML 호환 dict로 변환.
    schema 검증을 거쳐 반환. DB에는 author='user', user_id=... 로 저장."""
```

신규 라우트:

```
POST /situations/custom
  body: { description: "...", category_hint: "interview" | null }
  → SituationConfig (저장된 id 포함)
```

생성된 상황은 일반 카탈로그와 동일 스키마로 DB에 저장하되, `Situation.author` 컬럼 추가(`'official' | 'user'`). `GET /situations`에 `?author=official|user|all` 파라미터.

**프리미엄 게이트**: PoC에서는 X-Premium: true 헤더 또는 환경변수 `ENABLE_PREMIUM=1` 이면 허용, 아니면 402 응답. 실 결제 모듈은 비범위.

### Step 8 — 검증 가설 추가 (H5, H6)

기존 H1~H4에 다음 두 가설을 더한다.

- **H5. 표준 코칭 카드가 합성 bad 세션에서 합리적으로 트리거된다.**
  - `scripts/eval_coaching_tips.py` 신규: bad 세션 3개에 대해 활성 팁 종류를 출력, 카테고리별 기대 팁이 나오는지 README 표로 정리.
  - 합격 기준: bad emotional 세션에서 `clear_ending` 또는 `lead_with_conclusion` 중 하나 이상 트리거 / bad interview 세션에서 `shorten_answer` 또는 `lead_with_conclusion` 트리거.

- **H6. 사용자 맞춤 상황 생성이 사용 가능한 YAML을 만든다.**
  - `scripts/eval_custom_situation.py` 신규: 3가지 자연어 설명을 입력으로 넣어 생성, 각 결과가 (a) 모든 필수 필드를 갖추고 (b) opening_line으로 실제 대화 1턴까지 굴러가는지 확인.
  - 합격 기준: 3개 중 3개 성공.

README의 가설 표에 H5, H6 추가.

### Step 9 — 합성 데이터 확장

`scripts/synth_data.py`에 다음 추가:

- `--category` 옵션 (`emotional | interview | presentation`)
- bad 모드 프롬프트에 카테고리별 패턴 추가:
  - emotional bad: 필러 많음 + 회피
  - interview bad: 결론 없이 장황함 + 두서없음 (→ `shorten_answer`, `lead_with_conclusion` 트리거)
  - presentation bad: 끝음 흐림 + 청자 무시 (→ `clear_ending` 트리거)

이게 있어야 H5 검증이 데이터로 굴러간다.

### Step 10 — README 업데이트

다음 섹션 추가/갱신:

```
## v3 변경 요약
- VoiceUp → AEIOU 리브랜딩
- 면접/발표 카테고리 추가
- 답변 길이·반복어 metric 추가
- 표준 코칭 카드 3종
- 발음 분석 기본 활성화 (텍스트 가이드 only)
- 사용자 맞춤 상황 생성 (프리미엄)

## v3 가설별 검증
- H5: python scripts/eval_coaching_tips.py
- H6: python scripts/eval_custom_situation.py
... (기존 H1~H4 유지)
```

---

## 4. 회귀 체크리스트

마이그레이션 후 다음이 모두 통과해야 작업 완료.

- [ ] `pytest` 5초 이내 통과 (모킹된 상태)
- [ ] `python scripts/demo_run.py` 끝까지 실행, 정량 지표에 `answer_length_*`, `repeated_phrase_count` 노출
- [ ] `python scripts/eval_judge_variance.py --runs 5` 기존 합격 기준 유지
- [ ] `python scripts/eval_retake_diff.py` better_side == "retake"
- [ ] `python scripts/eval_coaching_tips.py` 합격 기준 충족 (§3.8)
- [ ] `python scripts/eval_custom_situation.py` 3/3 성공
- [ ] `GET /situations?category=interview` 응답에 신규 YAML 포함
- [ ] `GET /sessions/{id}/coaching` 응답에 `tips`와 `rewrites` 둘 다 포함
- [ ] `GET /sessions/{id}/pronunciation` 응답이 weak_words 리스트 반환
- [ ] `POST /situations/custom` (with `ENABLE_PREMIUM=1`) 성공
- [ ] 같은 요청을 `ENABLE_PREMIUM=0`으로 보내면 402 응답
- [ ] README의 가설 표가 H1~H6 모두 명시

---

## 5. 비범위 (이번 마이그레이션에서 하지 않는 것)

- Azure Pronunciation Assessment 실 연동 → v3.1
- 조음점 시각화 애니메이션 (Rive/Lottie) → 프로덕션 단계
- 결제 모듈 → 비범위
- WebSocket 실시간 대화 → 여전히 POST 턴 방식 유지
- 사용자 맞춤 상황의 톤·캐릭터 검증(안전성 필터) → v3.2

---

## 6. 끝나면 보고할 것

작업 완료 후 다음 3개를 콘솔로 출력:

1. 신규/수정된 파일 목록 (git diff --name-status)
2. 추가된 의존성 (있다면)
3. `scripts/eval_coaching_tips.py`와 `scripts/eval_custom_situation.py`의 실행 결과 요약

PoC의 목적은 여전히 **가설 검증**이다. 화려함보다 "데이터로 굴러가는가"가 우선.
