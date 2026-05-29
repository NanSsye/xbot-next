from __future__ import annotations

from pathlib import Path

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.exceptions import XBotError


def register_browser_tools(registry: ToolRegistry, *, workspace) -> None:
    session_manager = BrowserSessionManager(workspace=workspace)
    for tool in _browser_tools(workspace, session_manager=session_manager):
        registry.register(tool)


def _browser_tools(workspace, *, session_manager: "BrowserSessionManager") -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="browser.screenshot_url",
            description="Open a URL in a headless browser and save a PNG screenshot in the workspace.",
            risk_level="execute",
            handler=lambda payload: _screenshot_url(payload, workspace=workspace),
            toolset="browser",
            source="browser",
            timeout_seconds=120,
            metadata={"background_candidate": True, "background_reason": "browser screenshot may take time"},
            input_schema={
                "type": "object",
                "required": ["url", "path"],
                "properties": {
                    "url": {"type": "string"},
                    "path": {"type": "string"},
                    "full_page": {"type": "boolean", "default": True},
                    "width": {"type": "integer", "default": 1280},
                    "height": {"type": "integer", "default": 720},
                },
            },
        ),
        ToolDefinition(
            name="browser.run_actions",
            description=(
                "Run a stateless browser interaction sequence. Supported actions: goto, click, "
                "fill, press, wait_for_selector, wait, screenshot, text_content."
            ),
            risk_level="execute",
            handler=lambda payload: _run_actions(payload, workspace=workspace),
            toolset="browser",
            source="browser",
            timeout_seconds=180,
            metadata={"background_candidate": True, "background_reason": "browser interaction sequence may take time"},
            input_schema={
                "type": "object",
                "required": ["actions"],
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "width": {"type": "integer", "default": 1280},
                    "height": {"type": "integer", "default": 720},
                    "headless": {"type": "boolean", "default": True},
                },
            },
        ),
        ToolDefinition(
            name="browser.session_open",
            description="Open or reuse a persistent headless browser session and optionally navigate to a URL.",
            risk_level="execute",
            handler=session_manager.open,
            toolset="browser",
            source="browser",
            timeout_seconds=120,
            metadata={
                "session_persistent": True,
                "background_candidate": True,
                "background_reason": "browser startup may take time",
            },
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "url": {"type": "string"},
                    "width": {"type": "integer", "default": 1280},
                    "height": {"type": "integer", "default": 720},
                    "headless": {"type": "boolean", "default": True},
                },
            },
        ),
        ToolDefinition(
            name="browser.session_actions",
            description="Run actions in an existing persistent browser session.",
            risk_level="execute",
            handler=session_manager.run_actions,
            toolset="browser",
            source="browser",
            timeout_seconds=180,
            metadata={
                "session_persistent": True,
                "background_candidate": True,
                "background_reason": "browser session actions may take time",
            },
            input_schema={
                "type": "object",
                "required": ["session_id", "actions"],
                "properties": {
                    "session_id": {"type": "string"},
                    "actions": {"type": "array", "items": {"type": "object"}},
                },
            },
        ),
        ToolDefinition(
            name="browser.session_list",
            description="List currently open persistent browser sessions.",
            risk_level="read",
            handler=session_manager.list_sessions,
            toolset="browser",
            source="browser",
            cacheable=False,
            timeout_seconds=10,
            metadata={"session_persistent": True},
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="browser.session_close",
            description="Close one persistent browser session or all sessions.",
            risk_level="execute",
            handler=session_manager.close,
            toolset="browser",
            source="browser",
            timeout_seconds=30,
            invalidates_cache=True,
            metadata={"session_persistent": True},
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "all": {"type": "boolean", "default": False},
                },
            },
        ),
    ]


class BrowserSessionManager:
    def __init__(self, *, workspace) -> None:
        self.workspace = workspace
        self._playwright = None
        self._sessions: dict[str, dict] = {}

    async def open(self, payload: dict) -> dict:
        session_id = str(payload.get("session_id") or "default")
        session = self._sessions.get(session_id)
        if session is None:
            playwright = await self._ensure_playwright()
            width = int(payload.get("width", 1280))
            height = int(payload.get("height", 720))
            browser = await playwright.chromium.launch(headless=bool(payload.get("headless", True)))
            page = await browser.new_page(viewport={"width": width, "height": height})
            session = {"id": session_id, "browser": browser, "page": page, "width": width, "height": height}
            self._sessions[session_id] = session
        if payload.get("url"):
            response = await session["page"].goto(
                str(payload["url"]),
                wait_until=str(payload.get("wait_until", "networkidle")),
            )
            return {
                "session_id": session_id,
                "url": session["page"].url,
                "status": response.status if response else None,
                "opened": True,
            }
        return {"session_id": session_id, "url": session["page"].url, "opened": True}

    async def run_actions(self, payload: dict) -> dict:
        session_id = str(payload["session_id"])
        session = self._sessions.get(session_id)
        if session is None:
            raise XBotError(f"Browser session not found: {session_id}. Call browser.session_open first.")
        actions = payload.get("actions") or []
        if not isinstance(actions, list) or not actions:
            raise XBotError("browser.session_actions actions must be a non-empty array.")
        results = []
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise XBotError(f"Browser action at index {index} must be an object.")
            results.append(await _run_action(session["page"], action, workspace=self.workspace))
        return {"session_id": session_id, "url": session["page"].url, "actions": len(actions), "results": results}

    async def list_sessions(self, payload: dict) -> dict:
        return {
            "count": len(self._sessions),
            "sessions": [
                {
                    "session_id": session_id,
                    "url": session["page"].url,
                    "width": session["width"],
                    "height": session["height"],
                }
                for session_id, session in sorted(self._sessions.items())
            ],
        }

    async def close(self, payload: dict) -> dict:
        if payload.get("all"):
            closed = list(self._sessions)
            for session_id in closed:
                await self._close_one(session_id)
            await self._maybe_stop_playwright()
            return {"closed": closed, "count": len(closed)}
        session_id = str(payload.get("session_id") or "default")
        await self._close_one(session_id)
        await self._maybe_stop_playwright()
        return {"closed": [session_id], "count": 1}

    async def _ensure_playwright(self):
        if self._playwright is not None:
            return self._playwright
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise XBotError(
                "Browser tools require Playwright. Install it with: pip install playwright && playwright install chromium"
            ) from exc
        self._playwright = await async_playwright().start()
        return self._playwright

    async def _close_one(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        await session["browser"].close()

    async def _maybe_stop_playwright(self) -> None:
        if self._sessions or self._playwright is None:
            return
        await self._playwright.stop()
        self._playwright = None


async def _screenshot_url(payload: dict, *, workspace) -> dict:
    return await _run_actions(
        {
            "width": payload.get("width", 1280),
            "height": payload.get("height", 720),
            "actions": [
                {"type": "goto", "url": str(payload["url"])},
                {
                    "type": "screenshot",
                    "path": str(payload["path"]),
                    "full_page": bool(payload.get("full_page", True)),
                },
            ],
        },
        workspace=workspace,
    )


async def _run_actions(payload: dict, *, workspace) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise XBotError(
            "Browser tools require Playwright. Install it with: pip install playwright && playwright install chromium"
        ) from exc

    actions = payload.get("actions") or []
    if not isinstance(actions, list) or not actions:
        raise XBotError("browser.run_actions actions must be a non-empty array.")
    width = int(payload.get("width", 1280))
    height = int(payload.get("height", 720))
    headless = bool(payload.get("headless", True))
    results = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            for index, action in enumerate(actions):
                if not isinstance(action, dict):
                    raise XBotError(f"Browser action at index {index} must be an object.")
                results.append(await _run_action(page, action, workspace=workspace))
        finally:
            await browser.close()
    return {"actions": len(actions), "results": results}


async def _run_action(page, action: dict, *, workspace) -> dict:
    action_type = str(action.get("type") or action.get("action") or "")
    if action_type == "goto":
        response = await page.goto(str(action["url"]), wait_until=str(action.get("wait_until", "networkidle")))
        return {"type": action_type, "url": page.url, "status": response.status if response else None}
    if action_type == "click":
        await page.click(str(action["selector"]))
        return {"type": action_type, "selector": action["selector"]}
    if action_type == "fill":
        await page.fill(str(action["selector"]), str(action.get("value", "")))
        return {"type": action_type, "selector": action["selector"]}
    if action_type == "press":
        await page.press(str(action["selector"]), str(action["key"]))
        return {"type": action_type, "selector": action["selector"], "key": action["key"]}
    if action_type == "wait_for_selector":
        await page.wait_for_selector(str(action["selector"]), timeout=int(action.get("timeout_ms", 30000)))
        return {"type": action_type, "selector": action["selector"]}
    if action_type == "wait":
        await page.wait_for_timeout(int(action.get("timeout_ms", 1000)))
        return {"type": action_type, "timeout_ms": int(action.get("timeout_ms", 1000))}
    if action_type == "screenshot":
        target = workspace._resolve(str(action["path"]))
        workspace.policy.assert_file_write_allowed(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target), full_page=bool(action.get("full_page", True)))
        return {"type": action_type, "path": str(Path(target)), "written": True}
    if action_type == "text_content":
        text = await page.text_content(str(action["selector"]))
        max_chars = int(action.get("max_chars", 4000))
        return {
            "type": action_type,
            "selector": action["selector"],
            "text": (text or "")[:max_chars],
            "truncated": bool(text and len(text) > max_chars),
        }
    raise XBotError(f"Unsupported browser action type: {action_type}")
