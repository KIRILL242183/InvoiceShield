"""Application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

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
    version="0.7.0",
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
    response = await call_next(request)
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
    return {"status": "ok", "version": "0.7.0"}


@app.get("/ready", tags=["System"])
def ready(db: Session = Depends(get_db)):
    """Readiness checks the DB responds, rather than only the process."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    return {"status": "ready", "version": "0.7.0"}
