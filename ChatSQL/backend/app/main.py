import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.core.db import init_db
from app.core.errors import register_exception_handlers
from app.services.conversation_service import recover_running_answer_jobs
from app.services.query_service import check_metric_knowledge_startup


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Bank NL2SQL Lite", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    _mount_frontend(app)

    @app.on_event("startup")
    def recover_interrupted_answer_jobs() -> None:
        check_metric_knowledge_startup()
        recover_running_answer_jobs(stale_after_seconds=0)

    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = _frontend_dist()
    index = dist / "index.html"
    if not index.exists():
        return

    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="frontend_assets")

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            return FileResponse(index)
        target = dist / path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(index)


def _frontend_dist() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend" / "dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


app = create_app()
