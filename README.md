# VoiceUp PoC

한국어 대화 코칭 서비스 **VoiceUp**의 가설 검증용 PoC 백엔드. 사용자가 일상 상황(이별·사과·고백·갈등·거절)을 골라 AI와 음성 대화를 한 뒤, 표현 흐름·즉흥 대응·전달력에 대한 코칭 리포트를 받는다.

> 이 코드의 목적은 "보이는 것"이 아니라 **가설(H1~H4)을 검증**하는 것이다. 자세한 설계는 [`SPEC.md`](./SPEC.md) 참조.

## 빠른 시작

```bash
# 1. 의존성 설치 (uv 또는 pip)
pip install -r requirements.txt

# 2. (실 API 검증 시) 환경변수 설정
cp .env.example .env   # ANTHROPIC_API_KEY, OPENAI_API_KEY 입력

# 3. 합성 세션 생성 (실 API)
python scripts/synth_data.py --situation breakup_last_conversation \
    --goal clear_closure --quality good --out data/audio/demo

# 4. API 서버 실행
uvicorn app.main:app --reload

# 5. 전체 플로우 1회 시연 (실 API)
python scripts/demo_run.py
```

모킹만으로 외부 API 없이 전 구간을 돌리려면 `USE_MOCKS=1`을 설정한다.

## 테스트

```bash
pytest        # 외부 API 호출 없이 모킹으로 5초 내 통과
```

## 가설별 검증 방법

| 가설 | 명령 | 합격 기준 |
|---|---|---|
| H1. LLM-judge 일관성 | `python scripts/eval_judge_variance.py --runs 5` | 각 평가 차원 표준편차 ≤ 0.7 |
| H2. 정량 지표 합리성 | `python scripts/demo_run.py` → `data/results/*.json` 검토 | SPM 200~500, F0 80~300Hz, silence_ratio 0.1~0.4 |
| H3. 재작성 품질 | `GET /sessions/{id}/rewrites` 결과 정성 평가 | (정성) 원의도 유지 + 목표 부합 |
| H4. 리테이크 차이 | `python scripts/eval_retake_diff.py` | better_side == "retake" |

검증 결과 수치는 11단계에서 실 API 실행 후 채운다. (아래 "검증 결과" 섹션)

## 검증 결과

> _실 API 키(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)로 위 스크립트를 실행한 뒤 채울 것._

## 아키텍처 / 구현 노트

- **언어/스택**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x (SQLite).
- **외부 어댑터**(`app/conversation/`): STT(Whisper)·LLM(Claude Sonnet 4.6)·TTS(OpenAI)는 모두 Protocol 뒤에 숨고, 실 구현 + 결정론적 Mock 구현을 둔다. `USE_MOCKS=1`로 스위치.
- **분석 파이프라인**(`app/analysis/`): 신호 지표 → 필러 → 형태소/어휘 → LLM-judge(3회) → 재작성 → JSON 저장.

### PoC 환경상의 의도적 결정 (Windows / Python 3.13)

- **VAD**: `webrtcvad`는 Windows에서 MSVC 컴파일이 필요해 설치가 불안정하므로, `compute_silence_ratio`는 **순수 numpy 에너지 기반 VAD**로 구현했다. `webrtcvad`가 설치돼 있으면 자동으로 그쪽을 사용한다.
- **F0**: 기본은 **numpy 자기상관** 추정(결정론적·경량). `librosa`가 설치돼 있으면 `compute_f0_stats(method="pyin")`로 `librosa.pyin`을 쓸 수 있다.
- **형태소**: `kiwipiepy`가 없으면 공백 토큰화로 폴백(MATTR이 약간 거칠어짐). → 모킹 테스트는 항상 통과.

## 비범위

인증/멀티테넌트/WebSocket 스트리밍/프론트엔드/Docker/Alembic/F8 발음분석/모니터링은 PoC에서 구현하지 않는다 (SPEC §11).
