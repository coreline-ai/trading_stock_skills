# Trading Skills Engine + Dashboard

38개 트레이딩 스킬 카탈로그를 실행해 리포트를 생성하고, 대시보드에서 스킬 선택/실행/추천을 확인합니다.

기본 대시보드는 v2 엔진을 사용하며, 1차 실구현 스킬 4개(`economic-calendar-fetcher`, `earnings-calendar`, `market-news-analyst`, `us-stock-analysis`)는 실제 데이터 기반 분석기로 동작합니다. 나머지 스킬은 `not_implemented`로 명시됩니다.

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
- API 키 없음 + 캐시 없음: `status=unavailable` (500 미발생)
- 조회 실패 + stale 캐시 있음: `status=ok`, `cache_info.mode=stale`
- 미구현 스킬: `status=not_implemented`

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

```bash
export FMP_API_KEY=your_key
python scripts/run_full_engine.py
```
