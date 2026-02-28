# Trading Skills Engine + Dashboard

38개 트레이딩 스킬 카탈로그를 실행해 리포트를 생성하고, 대시보드에서 스킬 선택/실행/추천을 확인합니다.

기본 대시보드는 v2 엔진을 사용하며, 38개 전체 스킬이 실행 가능합니다. 10개 코어 스킬은 전용 분석기, 나머지는 market-state 기반 프록시 분석기로 동작합니다.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python scripts/run_full_engine.py
uvicorn trading_skills_engine.web.app:app --reload
```

Open:
- `http://127.0.0.1:8000/dashboard`
- `POST http://127.0.0.1:8000/api/v1/engine/run`
- `GET  http://127.0.0.1:8000/api/v1/skills`
- `POST http://127.0.0.1:8000/api/v2/skills/run`
- `GET  http://127.0.0.1:8000/api/v2/skills`
- `GET  http://127.0.0.1:8000/api/v2/engine/status`

## Data Flow

1. `scripts/run_full_engine.py`
2. `reports/skill_runs/latest_skill_runs.json` 생성 (38개 스킬 결과)
3. `reports/eod/latest_snapshot.json` 생성 (대시보드 경량 뷰)
4. `/dashboard`가 위 산출물을 읽어 렌더

## API

### v2
- `GET /api/v2/skills`
- `POST /api/v2/skills/run`
- `GET /api/v2/engine/status`

v2 실패 정책:
- API 키 없음 + 캐시 없음: 스킬별로 `degraded status=ok` 또는 `status=unavailable` (500 미발생)
- 조회 실패 + stale 캐시 있음: `status=ok`, `cache_info.mode=stale`
- 유효하지 않은 스킬 slug: `status=unavailable`, `reason_code=INVALID_SKILL`
- `market-news-analyst`는 FMP API 키가 없어도 RSS만으로 `status=ok`가 가능합니다(단, RSS 소스가 비면 unavailable).
- `economic-calendar-fetcher`, `earnings-calendar`, `us-stock-analysis`는 FMP API 키가 없어도 market state/RSS 프록시로 `status=ok` 동작합니다.
- 추천 생성 모드:
  - `skill_consensus`: 스킬 결과에서 자동 후보를 합산
  - `watchlist_consensus`: 사용자가 준 워치리스트만 대상으로 합산 평가
  - `role_gated_consensus`: `Primary 1개 + Confirm + Analysis` 역할 분리로 `PASS/WATCH/REJECT` 판정
    - 응답 `top_picks`에 `decision`, `primary_skill`, `confirm_votes`, `veto_count` 등 근거 메타 포함
  - `two_stage_intersection`: `Recommender(1~5) -> strict 교집합 -> Analyzer(1~3) -> all-pass strict 교집합`
    - 응답 `pipeline` 블록에 단계별 표 데이터(`recommender_outputs`, `recommender_intersection`, `recommender_union_top10`, `analysis_targets`, `analyzer_outputs_by_target`, `final_summary`) 포함
    - `analyzer_outputs_by_target`는 `target_group(intersection|top10)` 기준으로 분석 결과를 분리 제공합니다.
    - `final_summary`는 `intersection_symbols`와 `top5_from_top10`를 함께 반환합니다.
    - 검증용 옵션: `analyzer_pass_policy=pass_or_watch`로 WATCH 포함 교집합을 사용할 수 있고, `comparison_mode=true`로 `strict_all_pass` 대비 차이를 함께 확인할 수 있습니다.
- 추천 목록은 `top_picks_limit`(1~50)로 설정하며 기본값은 `5`입니다.
- v2는 `skills_v2/traits.py`의 38개 스킬 trait(역할/스타일/축 가중치/시그널/합의 가중치)를 기준으로
  프록시 스코어링과 추천 합산을 수행합니다.
- 대시보드에서 스킬은 `recommendation`(추천 기여 가능) / `analysis only`(분석 전용) 배지로 구분됩니다.
- 왼쪽 `권장 조합` 버튼으로 프리셋 조합을 빠르게 적용할 수 있습니다.

### v1 (호환 유지)
- `GET /api/v1/dashboard/header`
- `GET /api/v1/dashboard/strategy-weighting?profile=balanced|aggressive|defensive`
- `GET /api/v1/dashboard/market-overview`
- `GET /api/v1/dashboard/top-picks?limit=5`
- `GET /api/v1/dashboard/footer-nav`
- `GET /api/v1/dashboard/skills`
- `GET /api/v1/dashboard/skill-results`
- `GET /api/v1/engine/status`
- `POST /api/v1/engine/run`
- `GET /api/v1/skills`

## Tests

```bash
pytest -q
```

## Optional FMP Integration

`FMP_API_KEY` 설정 시 일부 시세를 실데이터로 업데이트합니다.

권장: 프로젝트 루트 `.env` 파일에 저장

```bash
cat > .env <<'EOF'
FMP_API_KEY=your_key
EOF
```

또는 기존 방식으로 셸 환경변수 export:

```bash
export FMP_API_KEY=your_key
python scripts/run_full_engine.py
```

대시보드 상단에서 `FMP ON/OFF` 토글을 눌러 실시간 FMP 호출을 즉시 비활성화/활성화할 수 있습니다.

- 설정 파일: `reports/runtime/fmp_settings.json`
- 사용량 파일: `reports/runtime/fmp_usage.json`
- 일일 호출 한도: 기본 `250`
- UI 표시: `사용량 121/250` 형식
