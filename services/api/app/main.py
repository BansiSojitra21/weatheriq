from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import WeatherIQError
from app.db.session import init_database
from app.services.anomaly_schedule import anomaly_detection_loop
from app.services.catalog import DISCLAIMER
from app.services.seed import seed_defaults

logger = logging.getLogger("weatheriq")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    init_database()
    seed_defaults()
    logger.info("WeatherIQ API ready")
    stop_anomaly_schedule = asyncio.Event()
    anomaly_task = None
    if get_settings().anomaly_schedule_enabled:
        anomaly_task = asyncio.create_task(anomaly_detection_loop(stop_anomaly_schedule))
    try:
        yield
    finally:
        stop_anomaly_schedule.set()
        if anomaly_task is not None:
            await anomaly_task


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="WeatherIQ API",
        version="1.0.0",
        description=(
            "Versioned API for weather history, analytics, short-horizon predictions, "
            "exploratory anomaly detection, and rule alerts. " + DISCLAIMER
        ),
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info("%s %s %s %sms", request.method, request.url.path, response.status_code, elapsed_ms)
        return response

    @application.exception_handler(WeatherIQError)
    async def handle_app_error(_request: Request, exc: WeatherIQError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    application.include_router(router)
    return application


app = create_app()
