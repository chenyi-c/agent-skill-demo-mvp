import logging
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.errors import AppError
from app.core.middleware import RequestIdMiddleware
from app.services.config_store import load_runtime_config
from app.services.discovery import discover_and_register_skills

logger = logging.getLogger("code_navi")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Register skills once at startup + preflight checks (Section 12.2, 4.4)."""
    load_runtime_config()
    discover_and_register_skills()

    # Preflight: check paper-search CLI (Section 4.4)
    # Check known install paths first (does not rely on PATH)
    cli = None
    candidates = [
        os.path.expandvars(r"%USERPROFILE%\.local\bin\paper-search.exe"),
        os.path.expandvars(r"%USERPROFILE%\.local\bin\paper-search"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            cli = c
            break
    if not cli:
        cli = shutil.which("paper-search")

    if cli:
        logger.info("paper-search CLI found at %s", cli)
    else:
        logger.warning(
            "paper-search CLI not found; academic search will report dependency unavailable"
        )

    yield


app = FastAPI(
    title="Code Navi — AI Agent Skill Demo MVP",
    description="Research clarification + constrained academic search, dual-mode routing.",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID (Section 11)
app.add_middleware(RequestIdMiddleware)

# Routes
app.include_router(router)


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    request_id = getattr(request.state, "request_id", "")
    logger.warning(
        "request_id=%s code=%s message=%s",
        request_id,
        exc.code.value,
        exc.message,
    )
    return JSONResponse(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": "error",
            "data": None,
            "error": {
                "code": exc.code.value,
                "message": exc.message,
                "retryable": exc.retryable,
                "details": exc.details,
            },
            "meta": {},
        },
        status_code=exc.http_status,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "")
    logger.exception("request_id=%s unhandled_error", request_id)
    return JSONResponse(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": "error",
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器处理请求时发生内部错误。",
                "retryable": False,
                "details": None,
            },
            "meta": {},
        },
        status_code=500,
    )

# Mount static folder for CSS/JS assets if any
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
