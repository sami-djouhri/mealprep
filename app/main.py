"""MealPrep MVP – FastAPI application."""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from sqlalchemy import text

from app.db import SessionLocal
from app.domain import DomainError
import app.tenant  # noqa: F401  (Multi-Tenant-Scoping fuer Session-Events)
from app.api.routes_api import router as api_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_inventory import router as inventory_router
from app.api.routes_planning import router as planning_router
from app.api.routes_profile import router as profile_router
from app.api.routes_recipes import html_router as recipes_html_router
from app.api.routes_recipes import ingredients_html_router
from app.api.routes_recipes import router as recipes_router
from app.api.routes_shopping import router as shopping_router
from app.services.lager_adapter import LagerUnavailable

# ---------------------------------------------------------------------------
# In-memory rate limiter: 60 requests per minute per IP
# ---------------------------------------------------------------------------
RATE_LIMIT = 60
RATE_WINDOW = 60  # seconds
_rate_store: dict[str, tuple[int, float]] = {}  # ip -> (count, window_start)
_rate_last_cleanup = time.monotonic()
RATE_CLEANUP_INTERVAL = 300  # 5 minutes


class AutheliaHeaderMiddleware(BaseHTTPMiddleware):
    """Liest Authelia-Header (Remote-User/Remote-Groups) in request.state.
    Soft-Auth: nur Logging-Stempel. Authelia/Edge-Nginx enforced den Zugriff
    am Edge (*.daheim.home). Bei lokalem 127.0.0.1-Direktaufruf sind die
    Header leer.
    """

    async def dispatch(self, request, call_next):
        request.state.user = request.headers.get("remote-user") or ""
        groups_header = request.headers.get("remote-groups") or ""
        request.state.groups = [g.strip() for g in groups_header.split(",") if g.strip()]
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _rate_last_cleanup
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        # Periodic cleanup of stale entries
        if now - _rate_last_cleanup > RATE_CLEANUP_INTERVAL:
            stale = [ip for ip, (_, ws) in _rate_store.items() if now - ws > RATE_WINDOW]
            for ip in stale:
                del _rate_store[ip]
            _rate_last_cleanup = now

        count, window_start = _rate_store.get(client_ip, (0, now))
        if now - window_start > RATE_WINDOW:
            # New window
            count, window_start = 1, now
        else:
            count += 1

        _rate_store[client_ip] = (count, window_start)

        if count > RATE_LIMIT:
            return JSONResponse(
                {"error": "Zu viele Anfragen. Bitte warte einen Moment."},
                status_code=429,
            )

        return await call_next(request)


import logging

from app.config import settings
from app.mandant_ableiten import einzigen_mandanten_ableiten

_start_log = logging.getLogger(__name__)

# ★ Einmalige Warnung beim Start, wenn kein Mandant fuer headerlose Aufrufe
# konfiguriert ist. Ohne sie waere der fail-closed-Zustand unsichtbar: interne
# Aufrufer (life-ops, assets-api) bekaemen leere Antworten, und leer sieht aus
# wie "nichts da" statt wie "nicht konfiguriert".
if not settings.DEFAULT_OWNER_SUB:
    _abgeleitet = einzigen_mandanten_ableiten()
    if _abgeleitet:
        settings.DEFAULT_OWNER_SUB = _abgeleitet
        _start_log.warning(
            "DEFAULT_OWNER_SUB war leer und wurde aus den Daten abgeleitet "
            "(genau ein Mandant vorhanden). Dauerhaft eintragen mit "
            "saganta/scripts/owner-kennung-eintragen.sh"
        )
    else:
        _start_log.warning(
            "DEFAULT_OWNER_SUB ist leer und nicht ableitbar. Headerlose interne "
            "Aufrufe sehen keine Daten. Eintragen mit "
            "saganta/scripts/owner-kennung-eintragen.sh"
        )

app = FastAPI(title="MealPrep", version="0.3.0")

app.add_middleware(RateLimitMiddleware)
app.add_middleware(AutheliaHeaderMiddleware)

# CORS – restrict to local dev server and reverse proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8096",
        "http://127.0.0.1:8096",
        "http://localhost",
        "https://localhost",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers – SPA API first, then legacy HTML
app.include_router(api_router)
app.include_router(dashboard_router)
app.include_router(inventory_router)
app.include_router(recipes_router)
app.include_router(recipes_html_router)
app.include_router(ingredients_html_router)
app.include_router(planning_router)
app.include_router(profile_router)
app.include_router(shopping_router)


@app.get("/health", tags=["health"])
def health():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": "Database unavailable"}, status_code=503)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(
        status_code=422,
        content={"error": exc.message, "details": exc.details},
    )


@app.exception_handler(LagerUnavailable)
async def lager_unavailable_handler(request: Request, exc: LagerUnavailable):
    return JSONResponse(
        status_code=503,
        content={"error": "Lager-Service nicht erreichbar", "details": {"message": str(exc)}},
    )
