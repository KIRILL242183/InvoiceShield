"""Application entrypoint."""
from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.version import APP_VERSION

from app.database import Base, engine
from app import models  # noqa: F401  (register metadata before create_all)
from app.routes_pdf import router as pdf_router
from app.routes_reports import router as reports_router
from app.routes_api import router as api_router
from app.routes_incidents import router as incident_api_router
from app.routes_investigations_web import router as investigation_web_router
from app.routes_auth import router as auth_router
from app.routes_web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Teaching/demo only: Alembic migrations will replace create_all in a later iteration.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="InvoiceShield",
    version=APP_VERSION,
    description="Демонстрационный сервис проверки рисков счетов поставщиков.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router)
app.include_router(incident_api_router)
app.include_router(auth_router)
app.include_router(web_router)
app.include_router(pdf_router)
app.include_router(reports_router)
app.include_router(investigation_web_router)


@app.middleware("http")
async def basic_security_headers(request, call_next):
    """Basic browser hardening; not a substitute for auth/CSRF/TLS."""
    request_id = uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    # Log a route template, not the raw URL/query string, cookies or body.
    route = request.scope.get("route")
    route_template = getattr(route, "path", "<unmatched>")
    logging.getLogger("invoiceshield.requests").info(
        "request_id=%s method=%s route=%s status=%s",
        request_id, request.method, route_template, response.status_code,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; form-action 'self'; base-uri 'none'; "
        "frame-ancestors 'none'; object-src 'none'"
    )
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/ready", tags=["System"])
def ready(db: Session = Depends(get_db)):
    """Readiness checks the DB actually responds, not just that the process lives."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        # Do not leak driver details, paths, credentials or SQL to clients.
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    return {"status": "ready", "version": APP_VERSION}
