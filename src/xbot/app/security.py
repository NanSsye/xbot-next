from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Request, WebSocket, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from xbot.core.config import Settings


PUBLIC_PATH_PREFIXES = (
    "/docs",
    "/openapi.json",
    "/redoc",
)


class ApiTokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._requires_auth(request):
            return await call_next(request)
        if not self.settings.api.token:
            return JSONResponse(
                {"success": False, "error": "api authentication is enabled but XBOT_API_TOKEN is empty"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if token_matches(request_token(request), self.settings.api.token):
            return await call_next(request)
        return JSONResponse(
            {"success": False, "error": "unauthorized"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _requires_auth(self, request: Request) -> bool:
        if request.method == "OPTIONS":
            return False
        if not self.settings.api.auth_enabled:
            return False
        path = request.url.path
        if not path.startswith("/api/"):
            return False
        return not any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def request_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("x-xbot-token", "").strip()


def websocket_token(websocket: WebSocket) -> str:
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_token = websocket.headers.get("x-xbot-token", "").strip()
    if header_token:
        return header_token
    return str(websocket.query_params.get("token") or "").strip()


def token_matches(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return secrets.compare_digest(candidate, expected)


async def authenticate_websocket(websocket: WebSocket) -> bool:
    settings: Settings = websocket.app.state.context.settings
    if not settings.api.auth_enabled:
        return True
    if not settings.api.token:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return False
    if token_matches(websocket_token(websocket), settings.api.token):
        return True
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False
