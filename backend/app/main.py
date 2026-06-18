from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import APP_ENV
from app.core.config import BACKEND_CORS_ORIGINS
from app.core.config import SEED_MOCK_ACCOUNTS
from app.db.database import ensure_database
from app.services.accounts import seed_mock_accounts
from app.services.auto_sync import auto_sync_service
from app.services.notification_settings import ensure_notification_settings

logger = logging.getLogger(__name__)
INTERNAL_ERROR_CODE = "internal_error"


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_database()
    if SEED_MOCK_ACCOUNTS:
        seed_mock_accounts()
    if APP_ENV != "cloud":
        ensure_notification_settings()
    auto_sync_service.start()
    try:
        yield
    finally:
        auto_sync_service.stop()


app = FastAPI(title="Fynish Mail Screening", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    headers = getattr(exc, "headers", None)
    if (
        isinstance(exc.detail, dict)
        and isinstance(exc.detail.get("message"), str)
        and isinstance(exc.detail.get("code"), str)
    ):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail["message"],
                "code": exc.detail["code"],
            },
            headers=headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled API error for method=%s path=%s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Request failed.",
            "code": INTERNAL_ERROR_CODE,
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
