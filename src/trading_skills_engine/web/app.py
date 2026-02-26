from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from trading_skills_engine.engine.orchestrator import SkillEngineOrchestrator
from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
from trading_skills_engine.skills_v2.contracts import EngineRunRequestV2
from trading_skills_engine.web.models import StrategyProfile
from trading_skills_engine.web.routes_dashboard import router as dashboard_router
from trading_skills_engine.web.routes_engine import router as engine_router
from trading_skills_engine.web.routes_engine_v2 import router as engine_v2_router
from trading_skills_engine.web.services.dashboard_bff import DashboardBFF, sparkline_to_svg_points
from trading_skills_engine.web.services.dashboard_bff_v2 import DashboardBFFV2


class DashboardTemplateHelpers:
    @staticmethod
    def return_color_class(value: float) -> str:
        return "text-accent-red" if value >= 0 else "text-blue-400"

    @staticmethod
    def return_badge_class(value: float) -> str:
        return "bg-blue-500/10 text-blue-500" if value >= 0 else "bg-sky-500/10 text-sky-500"

    @staticmethod
    def signed_percent(value: float) -> str:
        return f"{value:+.2f}%"


def create_app(snapshot_path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        report_path = Path("reports/skill_runs/latest_skill_runs.json")
        if not report_path.exists():
            orchestrator = SkillEngineOrchestrator()
            orchestrator.write_report(report_path)

        orchestrator_v2 = SkillEngineOrchestratorV2()
        if not orchestrator_v2.report_path.exists():
            orchestrator_v2.run_and_persist(
                EngineRunRequestV2(
                    selected_skills=[
                        "economic-calendar-fetcher",
                        "earnings-calendar",
                        "market-news-analyst",
                        "us-stock-analysis",
                    ],
                    as_of_date=date.today(),
                )
            )
        yield

    app = FastAPI(title="Trading Skills Dashboard", lifespan=lifespan)

    web_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    templates.env.globals["helpers"] = DashboardTemplateHelpers
    templates.env.globals["sparkline_to_svg_points"] = sparkline_to_svg_points

    app.state.dashboard_bff = DashboardBFF(snapshot_path=snapshot_path)
    app.state.dashboard_bff_v2 = DashboardBFFV2()
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
    app.include_router(dashboard_router)
    app.include_router(engine_router)
    app.include_router(engine_v2_router)

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page(
        request: Request,
        profile: StrategyProfile = Query(default=StrategyProfile.BALANCED),
        limit: int = Query(default=5, ge=1, le=20),
    ) -> HTMLResponse:
        del profile, limit
        model = request.app.state.dashboard_bff_v2.get_dashboard_view_model()
        context = {
            "request": request,
            "model": model,
        }
        return templates.TemplateResponse(request, "dashboard.html", context)

    @app.post("/dashboard/run")
    async def dashboard_run(request: Request) -> RedirectResponse:
        raw_body = (await request.body()).decode("utf-8")
        parsed = parse_qs(raw_body)
        selected = [str(item) for item in parsed.get("skills", []) if str(item).strip()]

        params_by_skill = {
            "economic-calendar-fetcher": {
                "from_days": _form_int(_first(parsed, "param__economic-calendar-fetcher__from_days"), 7),
                "to_days": _form_int(_first(parsed, "param__economic-calendar-fetcher__to_days"), 90),
                "country": _first(parsed, "param__economic-calendar-fetcher__country", "US").upper().strip(),
            },
            "earnings-calendar": {
                "days": _form_int(_first(parsed, "param__earnings-calendar__days"), 7),
                "min_market_cap": _form_int(_first(parsed, "param__earnings-calendar__min_market_cap"), 2_000_000_000),
            },
            "market-news-analyst": {
                "lookback_days": _form_int(_first(parsed, "param__market-news-analyst__lookback_days"), 10),
                "max_items": _form_int(_first(parsed, "param__market-news-analyst__max_items"), 80),
            },
            "us-stock-analysis": {
                "ticker": _first(parsed, "param__us-stock-analysis__ticker", "").upper().strip(),
            },
        }

        filtered_params = {slug: params_by_skill.get(slug, {}) for slug in selected}

        orchestrator_v2 = SkillEngineOrchestratorV2()
        orchestrator_v2.run_and_persist(
            EngineRunRequestV2(
                selected_skills=selected,
                as_of_date=date.today(),
                params_by_skill=filtered_params,
            )
        )
        return RedirectResponse(url="/dashboard", status_code=303)

    return app


app = create_app()


def _form_int(raw: object, default: int) -> int:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return default


def _first(parsed: dict[str, list[str]], key: str, default: str = "") -> str:
    values = parsed.get(key)
    if not values:
        return default
    return str(values[0])
