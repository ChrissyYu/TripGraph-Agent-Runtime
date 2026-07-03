"""Attach a unique request ID to each HTTP request."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from observability.context import current_trace_id


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        current_trace_id.set(request_id)
        try:
            response = await call_next(request)
        finally:
            current_trace_id.set(None)
        response.headers["X-Request-ID"] = request_id
        return response
