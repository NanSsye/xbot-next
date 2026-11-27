import json
import os
import time
from contextlib import suppress
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as ApiPath

router = APIRouter()
MAIL = Path("/run/xbot-updater")
Ticket = Annotated[str, ApiPath(pattern="^[0-9a-f]{64}$")]


@router.get("")
def available():
    try:
        if time.time() - (MAIL / "status/heartbeat").stat().st_mtime > 180:
            raise OSError("offline")
        view = json.loads((MAIL / "status/preview.json").read_bytes())
    except (OSError, ValueError) as error:
        raise HTTPException(503, "宿主机更新服务未连接") from error
    if view.get("error"):
        raise HTTPException(503, "暂存版本未通过宿主机检查")
    return {"data": view}


@router.get("/{ticket}")
def status(ticket: Ticket):
    try:
        job = json.loads((MAIL / "status" / (ticket + ".json")).read_bytes())
    except FileNotFoundError:
        if not (MAIL / "requests" / ticket).exists():
            raise HTTPException(404, "任务尚未提交") from None
        view = available()["data"]
        if view.get("confirmation") != ticket:
            # The worker commits a final receipt before retiring its preview.
            receipt = MAIL / "status" / (ticket + ".json")
            return {
                "data": json.loads(receipt.read_bytes())
                if receipt.exists()
                else {"status": "stale"}
            }
        job = {"status": "queued"}
    return {"data": job}


@router.post("/{ticket}", status_code=202)
def submit(ticket: Ticket, request: Request):
    host = request.url.hostname or ""
    if host != "localhost":
        try:
            ip_address(host)
        except ValueError as error:
            raise HTTPException(403, "请使用部署主机的 IP 地址确认更新") from error
    if (
        request.headers.get("origin") != (os.getenv('XBOT_UPDATE_ORIGIN') or str(request.base_url).rstrip("/"))
        or request.headers.get("x-xbot-action") != "framework-update"
        or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
    ):
        raise HTTPException(403, "请从本机 Xbot 页面确认更新")
    try:
        return status(ticket)
    except HTTPException as error:
        if error.status_code != 404:
            raise
    view = available()["data"]
    if not view.get("available") or view.get("confirmation") != ticket:
        raise HTTPException(409, "预览已变化，请重新检查更新")
    with suppress(FileExistsError):
        (MAIL / "requests" / ticket).touch(exist_ok=False)
    return {"data": {"status": "queued"}}
