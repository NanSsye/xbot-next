from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI

from xbot.core.config import load_settings
from xbot.core.logging import configure_logging, logger
from xbot.runtime.context import build_context
from xbot.storage.bootstrap import ensure_storage_ready


async def report_instance(token: str) -> None:
    async with httpx.AsyncClient(timeout=8) as client:
        while True:
            try:
                response = await client.post('https://xbot.catmi.si/api/instances/heartbeat', headers={'Authorization': f'Bearer {token}'})
                if response.status_code == 401:
                    logger.warning('Instance reporting stopped: invalid enrollment credential')
                    return
                response.raise_for_status()
            except httpx.HTTPError:
                logger.warning('Instance heartbeat unavailable')
            await asyncio.sleep(60)


def startup_release_digest() -> str | None:
    marker = Path(__file__).resolve().parents[3] / '.xbot-release-sha256'
    try:
        with marker.open('rb') as stream:
            digest = stream.read(66).removesuffix(b'\n')
    except FileNotFoundError:
        digest = b''
    return digest.decode('ascii') if re.fullmatch(b'[0-9a-f]{64}', digest) else None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    app.state.release_digest = await asyncio.to_thread(startup_release_digest)
    configure_logging(settings.xbot.debug)
    await ensure_storage_ready(settings)
    context = build_context(settings)
    app.state.context = context
    logger.info("Starting xbot-next backend")
    await context.engine.start()
    token = os.getenv('XBOT_INSTANCE_TOKEN')
    if not token:
        with suppress(FileNotFoundError):
            token = (await asyncio.to_thread(Path('/app/configs/.instance-token').read_text)).strip()
    heartbeat = asyncio.create_task(report_instance(token)) if token else None
    try:
        yield
    finally:
        logger.info("Stopping xbot-next backend")
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        active_context = app.state.context
        await active_context.engine.stop()
        await active_context.storage.close()
