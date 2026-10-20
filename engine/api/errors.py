"""One error shape for every non-2xx response: {"error": {"code", "message", "details"}}."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException

CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    422: "validation_error",
    500: "internal_error",
    501: "not_implemented",
}


class ErrorBody(BaseModel):
    code: str = Field(description="Stable, machine-readable error code, e.g. validation_error.")
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """An error the API returns on purpose, with its own status and code."""

    def __init__(
        self, status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []


def error_response(
    status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=jsonable_encoder(body))


# Documented on every route; POST routes also document 422.
RESPONSES: dict[int | str, dict[str, Any]] = {
    500: {"model": ErrorResponse, "description": "Unexpected engine error."},
}
INVALID: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "The request failed validation."},
}
NOT_IMPLEMENTED: dict[int | str, dict[str, Any]] = {
    501: {"model": ErrorResponse, "description": "Not implemented yet."}
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        return error_response(422, "validation_error", "The request failed validation.", details)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError) -> JSONResponse:
        # A pydantic error here comes from the engine's own output, so it's a bug, not bad input.
        if isinstance(exc, ValidationError):
            return error_response(500, "internal_error", "The engine produced an invalid plan.")
        return error_response(422, "invalid_request", str(exc))

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception) -> JSONResponse:
        return error_response(500, "internal_error", "Unexpected engine error.")
