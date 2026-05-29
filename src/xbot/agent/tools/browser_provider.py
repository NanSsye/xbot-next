from __future__ import annotations

from pathlib import Path

from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.exceptions import XBotError


def register_browser_tools(registry: ToolRegistry, *, workspace) -> None:
    registry.register(
        ToolDefinition(
            name="browser.screenshot_url",
            description="Open a URL in a headless browser and save a PNG screenshot in the workspace.",
            risk_level="execute",
            handler=lambda payload: _screenshot_url(payload, workspace=workspace),
            toolset="browser",
            source="browser",
            timeout_seconds=120,
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
        )
    )


async def _screenshot_url(payload: dict, *, workspace) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise XBotError(
            "Browser tools require Playwright. Install it with: pip install playwright && playwright install chromium"
        ) from exc

    target = workspace._resolve(str(payload["path"]))
    workspace.policy.assert_file_write_allowed(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    url = str(payload["url"])
    width = int(payload.get("width", 1280))
    height = int(payload.get("height", 720))
    full_page = bool(payload.get("full_page", True))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.goto(url, wait_until="networkidle")
            await page.screenshot(path=str(target), full_page=full_page)
        finally:
            await browser.close()
    return {"url": url, "path": str(Path(target)), "written": True}
