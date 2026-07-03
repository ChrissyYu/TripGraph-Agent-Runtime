"""Standardized API response envelope."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiMeta(BaseModel):
    request_id: str | None = None
    version: str | None = None
    environment: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    error: ApiError | None = None
    meta: ApiMeta | None = None


def ok(data: T, *, meta: ApiMeta | None = None) -> ApiResponse[T]:
    return ApiResponse(success=True, data=data, meta=meta)


def fail(code: str, message: str, *, details: dict[str, Any] | None = None) -> ApiResponse[Any]:
    return ApiResponse(
        success=False,
        error=ApiError(code=code, message=message, details=details),
    )
