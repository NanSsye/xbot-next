from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import re
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Request
import httpx

from xbot.app.deps import get_context
from xbot.runtime.context import AppContext
from xbot.services.release_stage import staged_release

router = APIRouter()
_install_lock = asyncio.Lock()


@router.post('/catalog/{digest}/install')
async def install_release(digest: str, request: Request, ctx: AppContext = Depends(get_context)) -> dict:
    if (request.headers.get('origin') != str(request.base_url).rstrip('/')
            or request.headers.get('x-xbot-action') != 'install'):
        raise HTTPException(403, '请从本机控制台安装')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise HTTPException(400, '发行标识无效')
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(
            Path('configs/release-signing.pub').read_text().strip(), validate=True))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, '未配置官方发行公钥') from exc
    catalog = (await official_catalog())['data']
    item = next((i for i in catalog if i.get('Digest') == digest and i.get('Kind') in {'plugin','skill'}), None)
    if item is None:
        raise HTTPException(404, '官方扩展不存在')
    async with _install_lock:
        data = bytearray()
        try:
            async with httpx.AsyncClient(timeout=15) as client, client.stream('GET', f'https://xbot.catmi.si/api/download/{digest}') as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(65536):
                    if len(data)+len(chunk) > 128 << 20:
                        raise HTTPException(413, '发行包过大')
                    data.extend(chunk)
        except httpx.HTTPError as exc:
            raise HTTPException(502, '下载发行包失败') from exc
        plugin = item['Kind'] == 'plugin'
        manager = ctx.plugins if plugin else ctx.skills
        root = Path(manager.config.directory).resolve()
        try:
            with staged_release(item, data, key, root.parent) as stage:
                manifest = manager.loader.load_manifest(stage)
                if (manifest.name,manifest.version) != (item['Name'],item['Version']):
                    raise ValueError('发行清单不匹配')
                if not plugin:
                    manager.loader.load_instructions(stage)
                target = root / manifest.name
                installed = manager.list_plugins() if plugin else manager.list_skills()
                if target.exists() or target.is_symlink() or any(i['name']==manifest.name for i in installed):
                    raise HTTPException(409, '已安装同名扩展，未覆盖')
                stage.rename(target)
                try:
                    if plugin:
                        if not await manager.reload(manifest.name):
                            raise ValueError('插件加载失败')
                    else:
                        await manager.load_all()
                        if not any(i['name']==manifest.name for i in manager.list_skills()):
                            raise ValueError('技能加载失败')
                except BaseException:
                    target.rename(stage)
                    raise
        except (OSError,ValueError,zipfile.BadZipFile) as exc:
            raise HTTPException(422, '官方包校验或加载失败') from exc
    return {'success':True,'data':{'name':manifest.name,'version':manifest.version}}


@router.get('/catalog')
async def official_catalog() -> dict:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get('https://xbot.catmi.si/api/catalog')
            response.raise_for_status()
            items = response.json()
            if not isinstance(items, list):
                raise ValueError('invalid catalog')
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, '暂时无法读取官方目录，请稍后重试。') from exc
    return {'success': True, 'data': items}


@router.get("")
async def list_skills(ctx: AppContext = Depends(get_context)) -> dict:
    return {"success": True, "data": ctx.skills.list_skills()}


@router.post("/reload")
async def reload_skills(ctx: AppContext = Depends(get_context)) -> dict:
    await ctx.skills.load_all()
    return {"success": True, "data": ctx.skills.list_skills()}


@router.post("/{name}/enable")
async def enable_skill(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    enabled = await ctx.skills.enable(name)
    if not enabled:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": True}}


@router.post("/{name}/disable")
async def disable_skill(name: str, ctx: AppContext = Depends(get_context)) -> dict:
    disabled = await ctx.skills.disable(name)
    if not disabled:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"success": True, "data": {"name": name, "enabled": False}}
