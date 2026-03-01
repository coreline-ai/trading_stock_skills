from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from trading_skills_engine.ai.report_service import AIReportService
from trading_skills_engine.config.fmp_runtime import FMPRuntimeSettingsStore
from trading_skills_engine.core.validators import parse_bool, parse_symbol_list
from trading_skills_engine.engine.orchestrator import SkillEngineOrchestrator
from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.contracts import EngineRunRequestV2
from trading_skills_engine.skills_v2.registry import is_implemented
from trading_skills_engine.skills_v2.traits import get_skill_trait
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
            default_v2_skills = [item.slug for item in SKILL_CATALOG if is_implemented(item.slug)]
            await asyncio.to_thread(
                orchestrator_v2.run_and_persist,
                EngineRunRequestV2(
                    selected_skills=default_v2_skills,
                    as_of_date=date.today(),
                ),
            )
        yield

    app = FastAPI(title="Trading Skills Dashboard", lifespan=lifespan)

    web_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    templates.env.globals["helpers"] = DashboardTemplateHelpers
    templates.env.globals["sparkline_to_svg_points"] = sparkline_to_svg_points

    app.state.dashboard_bff = DashboardBFF(snapshot_path=snapshot_path)
    app.state.dashboard_bff_v2 = DashboardBFFV2()
    app.state.ai_report_service = AIReportService()
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
    app.include_router(dashboard_router)
    app.include_router(engine_router)
    app.include_router(engine_v2_router)

    @app.middleware("http")
    async def add_default_web_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'"
            ),
        )
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")

        if path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=86400")
        elif path in {"/manifest.webmanifest", "/robots.txt", "/sitemap.xml", "/sw.js"}:
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        elif "text/html" in response.headers.get("content-type", ""):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v2/ai-report/latest")
    def ai_report_latest(request: Request) -> dict:
        service: AIReportService = request.app.state.ai_report_service
        latest = service.read_latest()
        if not latest:
            return {
                "ready": False,
                "message": "No AI report found",
                "api_configured": service.api_configured(),
            }
        return {
            "ready": True,
            "api_configured": service.api_configured(),
            "report": latest,
        }

    @app.get("/api/v2/ai-report/runtime")
    def ai_report_runtime(request: Request) -> dict:
        service: AIReportService = request.app.state.ai_report_service
        runtime = service.read_runtime()
        return {
            "api_configured": service.api_configured(),
            "runtime": runtime,
        }

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots_txt() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n")

    @app.get("/sitemap.xml")
    def sitemap_xml(request: Request) -> Response:
        base_url = str(request.base_url).rstrip("/")
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{base_url}/dashboard</loc></url>\n"
            f"  <url><loc>{base_url}/healthz</loc></url>\n"
            "</urlset>\n"
        )
        return Response(content=body, media_type="application/xml")

    @app.get("/manifest.webmanifest", response_class=JSONResponse)
    def web_manifest() -> JSONResponse:
        payload = {
            "name": "Coreline Stock AI",
            "short_name": "Coreline AI",
            "description": "2단계 교집합 기반 종목 추천/분석 대시보드",
            "lang": "ko-KR",
            "start_url": "/dashboard",
            "scope": "/",
            "display": "standalone",
            "background_color": "#F3F4F6",
            "theme_color": "#1D4ED8",
            "icons": [
                {
                    "src": "/static/favicon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        }
        return JSONResponse(payload)

    @app.get("/sw.js")
    def service_worker() -> Response:
        sw_path = web_dir / "static" / "sw.js"
        try:
            script = sw_path.read_text(encoding="utf-8")
        except Exception:
            script = "self.addEventListener('install', () => self.skipWaiting());"
        return Response(content=script, media_type="application/javascript")

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

    @app.post("/dashboard/fmp-toggle")
    async def dashboard_fmp_toggle(request: Request) -> RedirectResponse:
        raw_bytes = await request.body()
        if len(raw_bytes) > 64_000:
            return RedirectResponse(url="/dashboard", status_code=303)

        raw_body = raw_bytes.decode("utf-8", errors="ignore")
        try:
            parsed = parse_qs(raw_body, max_num_fields=128)
        except ValueError:
            parsed = {}

        enabled = _form_bool(_first(parsed, "enabled", "1"), default=True)
        FMPRuntimeSettingsStore().set_enabled(enabled)
        return RedirectResponse(url="/dashboard", status_code=303)

    @app.post("/dashboard/run")
    async def dashboard_run(request: Request) -> RedirectResponse:
        raw_bytes = await request.body()
        if len(raw_bytes) > 64_000:
            return RedirectResponse(url="/dashboard", status_code=303)

        raw_body = raw_bytes.decode("utf-8", errors="ignore")
        try:
            parsed = parse_qs(raw_body, max_num_fields=512)
        except ValueError:
            parsed = {}

        allowed_slugs = {item.slug for item in SKILL_CATALOG}
        recommender_skills: list[str] = []
        for raw in parsed.get("recommender_skills", []):
            slug = str(raw).strip()
            if not slug or slug not in allowed_slugs or slug in recommender_skills:
                continue
            recommender_skills.append(slug)

        analyzer_skills: list[str] = []
        for raw in parsed.get("analyzer_skills", []):
            slug = str(raw).strip()
            if not slug or slug not in allowed_slugs or slug in analyzer_skills:
                continue
            analyzer_skills.append(slug)

        role_valid_recommenders: list[str] = []
        role_valid_analyzers: list[str] = []
        for slug in recommender_skills:
            trait = get_skill_trait(slug)
            if trait and trait.recommendation_role in {"direct", "candidate"}:
                role_valid_recommenders.append(slug)
        for slug in analyzer_skills:
            trait = get_skill_trait(slug)
            if trait and trait.recommendation_role == "analysis_only":
                role_valid_analyzers.append(slug)

        if len(role_valid_recommenders) > 5:
            role_valid_recommenders = role_valid_recommenders[:5]
        if len(role_valid_analyzers) > 3:
            role_valid_analyzers = role_valid_analyzers[:3]

        selected: list[str] = []
        for slug in role_valid_recommenders + role_valid_analyzers:
            if slug not in selected:
                selected.append(slug)

        single_ticker = _first(parsed, "single_ticker", "").strip()
        multi_tickers = _first(parsed, "multi_tickers", "").strip()
        watchlist_symbols = _parse_watchlist_symbols(f"{single_ticker}\n{multi_tickers}")

        filtered_params = {
            "top-picks": {
                "recommender_skills": ",".join(role_valid_recommenders),
                "analyzer_skills": ",".join(role_valid_analyzers),
                "recommender_top_n": 25,
                "analyzer_pass_policy": "all_pass",
                "fallback_to_watch_on_empty": True,
                "comparison_mode": False,
                "watchlist_symbols": ",".join(watchlist_symbols),
            }
        }

        pipeline_config = {
            "recommender_skills": role_valid_recommenders,
            "analyzer_skills": role_valid_analyzers,
            "recommender_top_n": 25,
            "intersection_policy": "strict",
            "analyzer_pass_policy": "all_pass",
            "comparison_mode": False,
        }

        top_picks_mode = "two_stage_intersection"
        top_picks_limit = 5

        orchestrator_v2 = SkillEngineOrchestratorV2()
        run_request = EngineRunRequestV2(
            selected_skills=selected,
            as_of_date=date.today(),
            params_by_skill=filtered_params,
            top_picks_mode=top_picks_mode,
            watchlist_symbols=watchlist_symbols,
            top_picks_limit=top_picks_limit,
            pipeline_config=pipeline_config,
        )
        await asyncio.to_thread(orchestrator_v2.run_and_persist, run_request)
        return RedirectResponse(url="/dashboard", status_code=303)

    @app.post("/dashboard/ai-report/run")
    async def dashboard_ai_report_run(request: Request, background_tasks: BackgroundTasks) -> RedirectResponse:
        raw_bytes = await request.body()
        if len(raw_bytes) > 64_000:
            return RedirectResponse(url="/dashboard", status_code=303)
        service: AIReportService = request.app.state.ai_report_service
        runtime = service.read_runtime()
        if str(runtime.get("status") or "").lower() == "running":
            return RedirectResponse(url="/dashboard?ai_report=running", status_code=303)
        if not service.api_configured():
            service.generate_and_persist()
            return RedirectResponse(url="/dashboard?ai_report=missing_key", status_code=303)
        background_tasks.add_task(service.run_with_runtime)
        return RedirectResponse(url="/dashboard?ai_report=queued", status_code=303)

    @app.get("/dashboard/ai-report/run")
    def dashboard_ai_report_run_get() -> RedirectResponse:
        # Browser address-bar access sends GET; guide users back to dashboard action flow.
        return RedirectResponse(url="/dashboard", status_code=303)

    return app


app = create_app()


def _form_bool(raw: object, default: bool) -> bool:
    return parse_bool(raw, default=default)


def _parse_watchlist_symbols(raw_text: str) -> list[str]:
    return parse_symbol_list(raw_text, max_items=200, max_len=10)


def _first(parsed: dict[str, list[str]], key: str, default: str = "") -> str:
    values = parsed.get(key)
    if not values:
        return default
    return str(values[0])
