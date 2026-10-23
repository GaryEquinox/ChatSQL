from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, error_type: str = "app_error") -> None:
        self.message = message
        self.status_code = status_code
        self.error_type = error_type


def _safe_message(message: str) -> str:
    blocked = ("password", "api key", "authorization", "connection string")
    lowered = message.lower()
    if any(word in lowered for word in blocked):
        return "操作失败，错误详情已被隐藏。"
    return message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"type": exc.error_type, "message": _safe_message(exc.message)}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"type": exc.__class__.__name__, "message": _safe_message(str(exc))}},
        )
