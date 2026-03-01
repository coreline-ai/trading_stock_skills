# Trading Skills Engine + Dashboard

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116-009688?logo=fastapi&logoColor=white)](pyproject.toml)
[![Pytest](https://img.shields.io/badge/Pytest-83%20passed-0A9EDC?logo=pytest&logoColor=white)](tests)
[![Upstream](https://img.shields.io/badge/Upstream-claude--trading--skills-181717?logo=github&logoColor=white)](https://github.com/tradermonty/claude-trading-skills)

FastAPI 기반 트레이딩 스킬 실행 엔진과 대시보드입니다.  
현재 카탈로그는 **38개 스킬**이며, 대시보드는 **v2 2단계 교집합 파이프라인**을 기본 실행 경로로 사용합니다.

원본 아이디어/레퍼런스:
- https://github.com/tradermonty/claude-trading-skills

## Table of Contents
- [핵심 기능](#핵심-기능)
- [아키텍처 개요](#아키텍처-개요)
- [빠른 시작](#빠른-시작)
- [동작 화면](#동작-화면)
- [대시보드 사용법](#대시보드-사용법)
- [API 사용법](#api-사용법)
- [AI 최종 리포트](#ai-최종-리포트)
- [스킬 독립 실행 원칙](#스킬-독립-실행-원칙)
- [진단/테스트](#진단테스트)
- [운영 체크리스트](#운영-체크리스트)
- [FMP 연동 및 런타임 토글](#fmp-연동-및-런타임-토글)
- [환경 변수 전체](#환경-변수-전체)
- [상태 배지 해석](#상태-배지-해석)
- [산출물 경로](#산출물-경로)
- [트러블슈팅](#트러블슈팅)
- [레거시(v1) 엔드포인트](#레거시v1-엔드포인트)

## 핵심 기능
- **38개 스킬 카탈로그 실행**
  - 패밀리 분포: `market_analysis(11)`, `calendar(2)`, `strategy_risk(7)`, `market_timing(2)`, `earnings_momentum(2)`, `screening(8)`, `edge_research(4)`, `quality_orchestration(2)`
- **구현 방식**
  - 전용 구현 스킬: 10개 (`economic-calendar-fetcher`, `earnings-calendar`, `market-news-analyst`, `us-stock-analysis`, `market-breadth-analyzer`, `uptrend-analyzer`, `market-top-detector`, `ftd-detector`, `earnings-trade-analyzer`, `portfolio-manager`)
  - 나머지 스킬: trait 기반 `proxy` 분석기
- **대시보드 실행 모델**
  - 추천 스킬(최대 5) + 분석 스킬(최대 3) 분리 선택
  - `two_stage_intersection` 파이프라인 고정 실행
  - 티커 필터(개별/멀티) 지원
  - 한글 티커 별칭 표시, 단계별 테이블/최종 TOP5 제공
- **운영 안전장치**
  - FMP ON/OFF 토글 + 일일 호출량 표시(예: `121/250`)
  - API/네트워크 장애 시 stale cache/대체 소스 처리
  - 자동 회귀 검증 + uniqueness/independence 감사 스크립트

## 아키텍처 개요
1. `POST /dashboard/run` 또는 `POST /api/v2/skills/run`으로 실행 요청
2. `SkillEngineOrchestratorV2`가 선택 스킬 실행
3. 결과를 `reports/skill_runs/latest_skill_runs_v2.json` + `history_v2/`에 저장
4. `DashboardBFFV2`가 리포트를 정규화해 `/dashboard` 렌더
5. 진단 스크립트로 uniqueness/independence 품질 점검

## 빠른 시작
### 1) 설치
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### 2) 환경 변수 설정
```bash
cp .env.example .env
```

필수/권장:
- `FMP_API_KEY` (시장/캘린더/FMP 기반 스킬)
- `GLM_API_KEY` (AI 최종 리포트)

### 3) 서버 실행
```bash
# start | stop | restart | status | check
scripts/dashboard_server.sh restart
scripts/dashboard_server.sh status

# 서버 다운 시 자동 복구 1회 점검/복구
scripts/dashboard_server.sh ensure

# watchdog 상시 감시(15초 주기)
scripts/dashboard_watchdog.sh start
scripts/dashboard_watchdog.sh status
```

참고:
- `dashboard_server.sh` 기본 실행은 런타임 산출물을 `reports/runtime/*.runtime.json`에 저장합니다.
- 깃 추적 중인 `reports/skill_runs/latest_*.json`, `reports/ai/latest_ai_report.json` 파일 오염을 줄이기 위한 기본 동작입니다.
- 기존 경로를 유지하려면 실행 시 `SKILL_RUN_REPORT_V2_PATH`, `AI_REPORT_PATH`, `AI_REPORT_RUNTIME_PATH`를 직접 지정하세요.

접속:
- `http://127.0.0.1:8001/dashboard`
- `http://127.0.0.1:8001/healthz`

### 4) 직접 uvicorn 실행(대안)
```bash
python3.11 -m uvicorn trading_skills_engine.web.app:app --host 127.0.0.1 --port 8001
```

## 동작 화면
### Dashboard - Top View
![Dashboard Top](docs/screenshots/dashboard-top.png)

### Dashboard - Mid View
![Dashboard Middle](docs/screenshots/dashboard-middle.png)

### Dashboard - Result View
![Dashboard Result](docs/screenshots/result.png)

## 대시보드 사용법
대시보드 왼쪽 메뉴는 파이프라인 전용입니다.

1. **종목추천 스킬**에서 1~5개 선택  
2. **분석 스킬**에서 1~3개 선택  
3. 필요 시 **티커 필터** 입력 (`single_ticker`, `multi_tickers`)  
4. `선택한 스킬 실행` 클릭

결과 섹션:
- 추천 종목 카드
- 추천 스킬별 결과 테이블
- 추천 교집합
- 추천 합집합 정규화 TOP10
- 분석 스킬별 평가(타겟 분리: intersection/top10)
- 최종 결과 요약(최종 교집합 + 최종 TOP5)
- AI 최종 리포트(GLM 4.5)

## AI 최종 리포트
최종 추천 종목(TOP5)을 대상으로 AI 판정을 생성합니다.

- 실행: 대시보드 왼쪽 `AI 최종 리포트 생성` 버튼(수동 실행)
- 판정: `BUY / WATCH / AVOID` (UI에서 `매수 / 관망 / 비매수`)
- 근거 수집 우선순위:
  1. Yahoo Finance
  2. Stooq
  3. FMP (키+런타임 ON)
  4. 내부 파이프라인 점수
- 저장:
  - 최신: `reports/ai/latest_ai_report.json`
  - 이력: `reports/ai/history/*.json`

환경 변수:
```bash
GLM_API_KEY=your_key
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-4.5
GLM_TIMEOUT_SEC=90
GLM_MAX_RETRIES=2
```

참고:
- `GLM_API_KEY`가 없으면 버튼은 비활성화됩니다.
- TOP5 대상이 비어 있어도 버튼이 비활성화됩니다.
- 실행 상태는 `idle / running / failed`로 관리되며 `reports/ai/runtime.json`에 저장됩니다.

## API 사용법
### v2 엔드포인트
- `GET /api/v2/skills`
- `POST /api/v2/skills/run`
- `GET /api/v2/engine/status`
- `GET /api/v2/ai-report/latest`

### 대시보드 액션 엔드포인트
- `POST /dashboard/run` (스킬 실행)
- `POST /dashboard/fmp-toggle` (FMP 런타임 ON/OFF)
- `POST /dashboard/ai-report/run` (AI 최종 리포트 비동기 실행)

### v2 실행 예시 (two-stage)
```bash
curl -X POST http://127.0.0.1:8001/api/v2/skills/run \
  -H "Content-Type: application/json" \
  -d '{
    "selected_skills": [
      "sector-analyst",
      "technical-analyst",
      "vcp-screener",
      "macro-regime-detector"
    ],
    "as_of_date": "2026-02-28",
    "top_picks_mode": "two_stage_intersection",
    "pipeline_config": {
      "recommender_skills": ["sector-analyst", "technical-analyst", "vcp-screener"],
      "analyzer_skills": ["macro-regime-detector"],
      "recommender_top_n": 25,
      "intersection_policy": "strict",
      "analyzer_pass_policy": "all_pass",
      "comparison_mode": false
    }
  }'
```

### top_picks_mode 지원
- `skill_consensus`
- `watchlist_consensus`
- `role_gated_consensus`
- `two_stage_intersection`

## 스킬 독립 실행 원칙
현재 코드 기준 독립성 규칙:
- 각 스킬은 **자기 payload/자기 점수**로 실행됨
- 다른 스킬의 점수/판정이 해당 스킬 내부 계산에 영향을 주지 않음
- 스킬 간 결합은 파이프라인의 **최종 집계 단계(교집합/합집합/TOPN)** 에서만 수행

참고:
- 같은 시장 스냅샷을 읽는 구조이므로 종목군이 일부 겹칠 수는 있습니다.
- 이는 데이터 우주/시장 상태 공통 입력에 따른 현상이며, 스킬 간 직접 종속과는 다릅니다.

## 진단/테스트
### 전체 회귀
```bash
python3.11 -m pytest -q
```

### 변경 후 통합 검증 (권장)
```bash
scripts/verify_after_change.sh
```
실행 항목:
1. 핵심 테스트
2. 서버 재시작 + `/dashboard` 헬스 체크
3. `/dashboard` 엔드포인트 검증
4. uniqueness 감사
5. independence 감사

### 유니크니스 감사
```bash
python3.11 scripts/run_full_skill_uniqueness_report.py
```
- JSON: `reports/diagnostics/latest_skill_uniqueness_report.json`
- HTML: `reports/diagnostics/latest_skill_uniqueness_report.html`

### 독립성 감사
```bash
python3.11 scripts/run_skill_independence_report.py
```
- JSON: `reports/diagnostics/latest_skill_independence_report.json`
- HTML: `reports/diagnostics/latest_skill_independence_report.html`

## 운영 체크리스트
코드 수정 후 아래 순서로 확인하는 것을 권장합니다.

1. `python3.11 -m pytest -q`
2. `scripts/verify_after_change.sh`
3. `scripts/dashboard_server.sh status`
4. `curl -fsS http://127.0.0.1:8001/healthz`
5. 대시보드에서 스킬 실행 1회 + AI 리포트 실행 1회

## FMP 연동 및 런타임 토글
`.env` 또는 환경변수로 `FMP_API_KEY`를 설정하면 FMP 기반 조회를 활성화할 수 있습니다.

```bash
cat > .env <<'EOF'
FMP_API_KEY=your_key
EOF
```

런타임 제어:
- 대시보드 상단 `FMP ON/OFF` 토글
- 사용량 라벨 `used_today/daily_limit`

관련 파일:
- 설정: `reports/runtime/fmp_settings.json`
- 사용량: `reports/runtime/fmp_usage.json`

기본값:
- 일일 호출 한도: `250`
- Base URL: `https://financialmodelingprep.com/stable`

추가 환경 변수:
- `TRADING_SKILLS_ENV_FILE` : `.env` 경로 오버라이드
- `TRADING_SKILLS_DISABLE_DOTENV=1` : `.env` 자동 로드 비활성화
- `SKILL_RUN_REPORT_V2_PATH` : v2 리포트 저장 위치 변경
- `FMP_RUNTIME_SETTINGS_PATH` : FMP 런타임 설정 파일 경로 변경
- `FMP_USAGE_PATH` : FMP 사용량 파일 경로 변경
- `AI_REPORT_PATH` : AI 리포트 저장 위치 변경
- `AI_REPORT_RUNTIME_PATH` : AI 실행 상태(runtime) 파일 경로 변경

## 환경 변수 전체
| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `FMP_API_KEY` | 없음 | FMP API 연동 키 |
| `GLM_API_KEY` | 없음 | GLM 4.5 AI 리포트 키 |
| `GLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | GLM API Base URL |
| `GLM_MODEL` | `glm-4.5` | GLM 모델명 |
| `GLM_TIMEOUT_SEC` | `90` | GLM 호출 타임아웃(초, 최소 15 / 최대 180) |
| `GLM_MAX_RETRIES` | `2` | GLM 타임아웃/일시적 네트워크 오류 재시도 횟수 (최대 4) |
| `TRADING_SKILLS_LOG_LEVEL` | `INFO` | 애플리케이션 로그 레벨 (`DEBUG/INFO/WARNING/ERROR`) |
| `TRADING_SKILLS_ENV_FILE` | `.env` | 환경 파일 경로 오버라이드 |
| `TRADING_SKILLS_DISABLE_DOTENV` | `0` | `.env` 자동 로드 비활성화 (`1`이면 비활성) |
| `SKILL_RUN_REPORT_V2_PATH` | `reports/skill_runs/latest_skill_runs_v2.json` | v2 최신 리포트 경로 |
| `SKILL_RUN_HISTORY_MAX_FILES` | `500` | v2 history 보관 최대 파일 수 (`0`이면 개수 제한 비활성) |
| `SKILL_RUN_HISTORY_MAX_DAYS` | `0` | v2 history 보관 일수 (`0`이면 기간 제한 비활성) |
| `FMP_RUNTIME_SETTINGS_PATH` | `reports/runtime/fmp_settings.json` | FMP 런타임 설정 경로 |
| `FMP_USAGE_PATH` | `reports/runtime/fmp_usage.json` | FMP 호출 사용량 경로 |
| `AI_REPORT_PATH` | `reports/ai/latest_ai_report.json` | AI 최신 리포트 경로 |
| `AI_REPORT_RUNTIME_PATH` | `reports/ai/runtime.json` | AI 실행 상태 경로 |
| `AI_REPORT_RUNNING_TTL_SEC` | `600` | `running` 상태 stale 자동 복구 기준(초, 기본 10분) |
| `AI_REPORT_RUNNING_DELAY_WARN_SEC` | `300` | 대시보드에서 실행 지연 경고를 표시하는 기준(초) |
| `AI_REPORT_HISTORY_MAX_FILES` | `500` | AI history 보관 최대 파일 수 (`0`이면 개수 제한 비활성) |
| `AI_REPORT_HISTORY_MAX_DAYS` | `0` | AI history 보관 일수 (`0`이면 기간 제한 비활성) |

`.env` 파서 제한 사항:
- 현재 내장 파서는 기본 `KEY=VALUE`만 지원합니다.
- 멀티라인 값, `${VAR}` 확장, 복잡한 escape 시퀀스는 지원하지 않습니다.

## 상태 배지 해석
대시보드 헤더의 상태 배지는 아래 의미를 가집니다.

- `API Key configured/missing`
  - 현재 프로세스에서 API 키를 읽었는지 여부
- `FMP: live/stale/unavailable`
  - `live`: 실시간 조회 성공
  - `stale`: 캐시/샘플 등 대체 데이터
  - `unavailable`: 조회 실패 또는 미구성
- `RSS: live/stale/unavailable`
  - 뉴스 소스 상태
- `OK / Unavailable / Not Implemented`
  - 이번 실행에서 각 상태로 종료된 스킬 개수

## 산출물 경로
- v2 최신 리포트: `reports/skill_runs/latest_skill_runs_v2.json`
- v2 히스토리: `reports/skill_runs/history_v2/*.json`
- 진단 리포트: `reports/diagnostics/*.json`, `reports/diagnostics/*.html`
- 런타임(FMP): `reports/runtime/*.json`
- 레거시(v1) 리포트: `reports/skill_runs/latest_skill_runs.json`

## 트러블슈팅
### `ERR_CONNECTION_REFUSED` / 대시보드 미접속
```bash
scripts/dashboard_server.sh status
scripts/dashboard_server.sh restart
scripts/dashboard_server.sh ensure
scripts/dashboard_watchdog.sh status || scripts/dashboard_watchdog.sh start
curl -fsS http://127.0.0.1:8001/healthz
```

watchdog 로그:
```bash
tail -f /tmp/trading_skills_watchdog_8001.log
```

### `API Key missing`
- `.env`에 `FMP_API_KEY` 설정 확인
- 대시보드 상단 `API Key configured/missing` 배지 확인
- 토글이 OFF면 ON으로 전환

### 호출 한도 초과 (`FMP_DAILY_LIMIT_REACHED`)
- 다음 중 하나 수행:
  - FMP 토글 OFF
  - 호출량 초기화(날짜 경과)
  - 한도 상향(설정 파일)

### `AI 최종 리포트 생성` 클릭 후 반응이 없거나 실패
1. `GLM_API_KEY` 설정 여부 확인
2. `AI_REPORT_RUNTIME_PATH` 경로의 상태 파일에서 `status(running/failed)` 확인  
   (`dashboard_server.sh` 기본 실행 시: `reports/runtime/ai_runtime.runtime.json`)
3. `GET /api/v2/ai-report/latest`로 최신 실패 코드 확인
4. `GLM_TIMEOUT_SEC` 값을 늘리고(`90`~`120` 권장), `GLM_MAX_RETRIES=2` 이상으로 재시도
5. 여전히 실패하면 FMP 토글/네트워크 상태를 점검하고 다시 실행

### `AI 리포트 생성 진행 중` 상태가 오래 유지될 때
- 기본적으로 `running` 상태가 10분(`AI_REPORT_RUNNING_TTL_SEC`) 이상 갱신되지 않으면 자동으로 stale 처리되어 재실행 가능 상태로 전환됩니다.
- 즉시 초기화가 필요하면 `AI_REPORT_RUNTIME_PATH` 파일을 삭제한 뒤 다시 실행합니다.  
  (`dashboard_server.sh` 기본 실행 시: `reports/runtime/ai_runtime.runtime.json`)

## 레거시(v1) 엔드포인트
호환을 위해 v1 API도 유지합니다.

- `GET /api/v1/skills`
- `POST /api/v1/engine/run`
- `GET /api/v1/engine/status`
- `GET /api/v1/dashboard/header`
- `GET /api/v1/dashboard/strategy-weighting`
- `GET /api/v1/dashboard/market-overview`
- `GET /api/v1/dashboard/top-picks`
- `GET /api/v1/dashboard/footer-nav`
- `GET /api/v1/dashboard/skills`
- `GET /api/v1/dashboard/skill-results`
