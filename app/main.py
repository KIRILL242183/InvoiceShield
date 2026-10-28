"""Application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app import models  # noqa: F401  (register metadata before create_all)
from app.routes_api import router as api_router
from app.routes_web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Teaching/demo only: Alembic migrations will replace create_all in a later iteration.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="InvoiceShield",
    version="0.1.1",
    description="Демонстрационный сервис проверки рисков счетов поставщиков.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router)
app.include_router(web_router)


@app.middleware("http")
async def basic_security_headers(request, call_next):
    """Basic browser hardening; not a substitute for auth/CSRF/TLS."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "version": "0.1.1"}
