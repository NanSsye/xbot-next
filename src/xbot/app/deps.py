from __future__ import annotations

from fastapi import Request

from xbot.runtime.context import AppContext


def get_context(request: Request) -> AppContext:
    return request.app.state.context

