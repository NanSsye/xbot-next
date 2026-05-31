from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


console = Console()


LOCAL_PROFILE = "local"
PRODUCTION_PROFILE = "production"
WECHAT_NONE = "none"
WECHAT_ILINK = "ilink"
WECHAT_869 = "869"
WECHAT_BOTH = "both"


def run_setup(
    *,
    profile: str | None = None,
    wechat: str | None = None,
    env_path: str | None = None,
    yes: bool = False,
) -> Path:
    target = Path(env_path or ".env").resolve()
    values = _read_env(target)
    console.print(
        Panel(
            "[bold]xbot 设置向导[/bold]\n"
            "首次运行会配置模型、数据库、队列和微信通道。\n"
            "[dim]已有配置会尽量保留，只有本向导涉及的项目会更新。[/dim]",
            title="欢迎",
            border_style="cyan",
        )
    )

    profile = _choose_profile(profile, yes=yes)
    wechat = _choose_wechat(wechat, yes=yes)

    updates: dict[str, str] = {
        "XBOT_LOAD_DOTENV": "true",
        "XBOT_SERVER_HOST": values.get("XBOT_SERVER_HOST") or "0.0.0.0",
        "XBOT_SERVER_PORT": values.get("XBOT_SERVER_PORT") or "8080",
        "XBOT_DATABASE_AUTO_BOOTSTRAP": "true",
        "XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP": "true",
    }
    if profile == LOCAL_PROFILE:
        updates.update(
            {
                "XBOT_STORAGE_TYPE": "sqlite",
                "XBOT_DATABASE_URL": "sqlite+aiosqlite:///data/xbot.db",
                "XBOT_ADMIN_DATABASE_URL": "",
                "XBOT_CONVERSATION_STORE": "sqlite",
                "XBOT_QUEUE_TYPE": "memory",
            }
        )
    else:
        updates.update(
            {
                "XBOT_STORAGE_TYPE": "postgresql",
                "XBOT_CONVERSATION_STORE": "postgresql",
                "XBOT_QUEUE_TYPE": "redis",
                "XBOT_DATABASE_URL": _ask(
                    "PostgreSQL app URL",
                    values.get("XBOT_DATABASE_URL")
                    or "postgresql+asyncpg://xbot:xbot@127.0.0.1:5432/xbot",
                    yes=yes,
                ),
                "XBOT_ADMIN_DATABASE_URL": _ask(
                    "PostgreSQL admin URL",
                    values.get("XBOT_ADMIN_DATABASE_URL")
                    or "postgresql://postgres:change-me@127.0.0.1:5432/postgres",
                    yes=yes,
                ),
                "XBOT_REDIS_URL": _ask(
                    "Redis URL",
                    values.get("XBOT_REDIS_URL") or "redis://127.0.0.1:6379/15",
                    yes=yes,
                ),
            }
        )

    updates.update(_llm_updates(values, yes=yes))
    updates.update(_wechat_updates(values, wechat=wechat, yes=yes))
    _write_env(target, values, updates)

    _print_summary(target=target, profile=profile, wechat=wechat, updates=updates)
    if wechat in {WECHAT_ILINK, WECHAT_BOTH}:
        console.print("[yellow]iLink 已启用：[/yellow]如果需要登录，xbot run 会在终端打印二维码链接。")
    return target


def _choose_profile(profile: str | None, *, yes: bool) -> str:
    profile = (profile or "").strip().lower()
    if profile in {LOCAL_PROFILE, PRODUCTION_PROFILE}:
        return profile
    if yes:
        return LOCAL_PROFILE
    console.print(
        Panel(
            "1. [bold green]简易版[/bold green] - SQLite + 本地队列，适合首次运行和个人电脑\n"
            "2. [bold]生产版[/bold] - PostgreSQL + Redis，适合服务器长期运行",
            title="步骤 1/3：运行模式",
            border_style="green",
        )
    )
    choice = typer.prompt("请选择运行模式", default="1")
    return PRODUCTION_PROFILE if choice.strip() in {"2", PRODUCTION_PROFILE, "prod"} else LOCAL_PROFILE


def _choose_wechat(wechat: str | None, *, yes: bool) -> str:
    wechat = (wechat or "").strip().lower()
    aliases = {"wechat869": WECHAT_869, "wechat_ilink": WECHAT_ILINK}
    wechat = aliases.get(wechat, wechat)
    if wechat in {WECHAT_NONE, WECHAT_ILINK, WECHAT_869, WECHAT_BOTH}:
        return wechat
    if yes:
        return WECHAT_ILINK
    console.print(
        Panel(
            "1. 暂不开启\n"
            "2. [bold green]iLink 扫码登录[/bold green]\n"
            "3. 869 服务\n"
            "4. 两个都开启",
            title="步骤 2/3：微信通道",
            border_style="green",
        )
    )
    choice = typer.prompt("请选择微信通道", default="2").strip().lower()
    return {"1": WECHAT_NONE, "2": WECHAT_ILINK, "3": WECHAT_869, "4": WECHAT_BOTH}.get(
        choice, choice if choice in {WECHAT_NONE, WECHAT_ILINK, WECHAT_869, WECHAT_BOTH} else WECHAT_ILINK
    )


def _llm_updates(values: dict[str, str], *, yes: bool) -> dict[str, str]:
    if not yes:
        console.print(
            Panel(
                "支持任意 OpenAI-compatible /chat/completions 服务。\n"
                "后续模型、密钥、地址变化时，可以直接编辑 .env。",
                title="步骤 3/3：模型",
                border_style="green",
            )
        )
    enabled_default = values.get("XBOT_LLM_ENABLED") or "true"
    enabled = _ask("是否启用 LLM", enabled_default, yes=yes)
    updates = {
        "XBOT_LLM_ENABLED": enabled,
        "XBOT_LLM_BASE_URL": _ask(
            "LLM 接口地址",
            values.get("XBOT_LLM_BASE_URL") or "https://api.openai.com/v1",
            yes=yes,
        ),
        "XBOT_LLM_MODEL": _ask(
            "模型名称",
            values.get("XBOT_LLM_MODEL") or "gpt-4.1-mini",
            yes=yes,
        ),
        "XBOT_LLM_CONTEXT_WINDOW_TOKENS": _ask(
            "模型上下文窗口 token",
            values.get("XBOT_LLM_CONTEXT_WINDOW_TOKENS") or "128000",
            yes=yes,
        ),
        "XBOT_LLM_TIMEOUT_SECONDS": values.get("XBOT_LLM_TIMEOUT_SECONDS") or "60",
        "XBOT_LLM_MAX_ATTEMPTS": values.get("XBOT_LLM_MAX_ATTEMPTS") or "3",
        "XBOT_LLM_RETRY_BACKOFF_SECONDS": values.get("XBOT_LLM_RETRY_BACKOFF_SECONDS") or "1.0",
    }
    api_key = values.get("XBOT_LLM_API_KEY") or ""
    if yes:
        updates["XBOT_LLM_API_KEY"] = api_key or "change-me"
    else:
        updates["XBOT_LLM_API_KEY"] = typer.prompt("LLM API Key", default=api_key or "change-me", hide_input=True)
    return updates


def _wechat_updates(values: dict[str, str], *, wechat: str, yes: bool) -> dict[str, str]:
    enable_ilink = wechat in {WECHAT_ILINK, WECHAT_BOTH}
    enable_869 = wechat in {WECHAT_869, WECHAT_BOTH}
    updates = {
        "XBOT_WECHAT_ILINK_ENABLED": str(enable_ilink).lower(),
        "XBOT_WECHAT869_ENABLED": str(enable_869).lower(),
    }
    if enable_ilink:
        updates.update(
            {
                "XBOT_WECHAT_ILINK_BASE_URL": values.get("XBOT_WECHAT_ILINK_BASE_URL")
                or "https://ilinkai.weixin.qq.com",
                "XBOT_WECHAT_ILINK_CDN_BASE_URL": values.get("XBOT_WECHAT_ILINK_CDN_BASE_URL")
                or "https://novac2c.cdn.weixin.qq.com/c2c",
                "XBOT_WECHAT_ILINK_POLL_INTERVAL_SECONDS": values.get(
                    "XBOT_WECHAT_ILINK_POLL_INTERVAL_SECONDS"
                )
                or "1.0",
                "XBOT_WECHAT_ILINK_CONNECT_TIMEOUT_SECONDS": values.get(
                    "XBOT_WECHAT_ILINK_CONNECT_TIMEOUT_SECONDS"
                )
                or "45",
                "XBOT_WECHAT_ILINK_MEDIA_ENABLED": "true",
            }
        )
    if enable_869:
        updates.update(
            {
                "XBOT_WECHAT869_HOST": _ask(
                    "869 服务地址", values.get("XBOT_WECHAT869_HOST") or "127.0.0.1", yes=yes
                ),
                "XBOT_WECHAT869_PORT": _ask(
                    "869 服务端口", values.get("XBOT_WECHAT869_PORT") or "5253", yes=yes
                ),
                "XBOT_WECHAT869_WS_URL": _ask(
                    "869 WebSocket 地址",
                    values.get("XBOT_WECHAT869_WS_URL") or "ws://127.0.0.1:5253/ws/GetSyncMsg",
                    yes=yes,
                ),
                "XBOT_WECHAT869_TOKEN_KEY": _ask(
                    "869 token key", values.get("XBOT_WECHAT869_TOKEN_KEY") or "", yes=yes
                ),
                "XBOT_WECHAT869_BOT_WXID": _ask(
                    "869 机器人 wxid（可选，群 @ 优先从 WS atuserlist 自动识别）",
                    values.get("XBOT_WECHAT869_BOT_WXID") or "",
                    yes=yes,
                ),
                "XBOT_WECHAT869_BOT_NICKNAME": _ask(
                    "869 机器人昵称（可选，仅作无 atuserlist 时兜底）",
                    values.get("XBOT_WECHAT869_BOT_NICKNAME") or "",
                    yes=yes,
                ),
                "XBOT_WECHAT869_MEDIA_ENABLED": "true",
            }
        )
    return updates


def _ask(label: str, default: str, *, yes: bool) -> str:
    if yes:
        return default
    return typer.prompt(label, default=default)


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env(path: Path, values: dict[str, str], updates: dict[str, str]) -> None:
    merged = {**values, **updates}
    ordered_keys = [
        "XBOT_LOAD_DOTENV",
        "XBOT_SERVER_HOST",
        "XBOT_SERVER_PORT",
        "XBOT_STORAGE_TYPE",
        "XBOT_DATABASE_URL",
        "XBOT_ADMIN_DATABASE_URL",
        "XBOT_DATABASE_AUTO_BOOTSTRAP",
        "XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP",
        "XBOT_CONVERSATION_STORE",
        "XBOT_QUEUE_TYPE",
        "XBOT_REDIS_URL",
        "XBOT_LLM_ENABLED",
        "XBOT_LLM_BASE_URL",
        "XBOT_LLM_MODEL",
        "XBOT_LLM_CONTEXT_WINDOW_TOKENS",
        "XBOT_LLM_TIMEOUT_SECONDS",
        "XBOT_LLM_MAX_ATTEMPTS",
        "XBOT_LLM_RETRY_BACKOFF_SECONDS",
        "XBOT_LLM_API_KEY",
        "XBOT_WECHAT_ILINK_ENABLED",
        "XBOT_WECHAT_ILINK_BASE_URL",
        "XBOT_WECHAT_ILINK_CDN_BASE_URL",
        "XBOT_WECHAT_ILINK_POLL_INTERVAL_SECONDS",
        "XBOT_WECHAT_ILINK_CONNECT_TIMEOUT_SECONDS",
        "XBOT_WECHAT_ILINK_MEDIA_ENABLED",
        "XBOT_WECHAT869_ENABLED",
        "XBOT_WECHAT869_HOST",
        "XBOT_WECHAT869_PORT",
        "XBOT_WECHAT869_WS_URL",
        "XBOT_WECHAT869_TOKEN_KEY",
        "XBOT_WECHAT869_BOT_WXID",
        "XBOT_WECHAT869_BOT_NICKNAME",
        "XBOT_WECHAT869_MEDIA_ENABLED",
    ]
    lines = ["# Generated by xbot setup.", "# Edit this file directly when needed.", ""]
    written = set()
    for key in ordered_keys:
        if key in merged:
            lines.append(f"{key}={merged[key]}")
            written.add(key)
    extra_keys = sorted(key for key in merged if key not in written)
    if extra_keys:
        lines.append("")
        lines.append("# Existing values preserved by setup.")
        for key in extra_keys:
            lines.append(f"{key}={merged[key]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _print_summary(*, target: Path, profile: str, wechat: str, updates: dict[str, str]) -> None:
    table = Table(title="xbot 设置摘要", show_header=True, header_style="bold cyan")
    table.add_column("项目")
    table.add_column("值")
    table.add_row("配置文件", str(target))
    table.add_row("运行模式", "简易版" if profile == LOCAL_PROFILE else "生产版")
    table.add_row("数据库", updates.get("XBOT_STORAGE_TYPE", ""))
    table.add_row("队列", updates.get("XBOT_QUEUE_TYPE", ""))
    table.add_row("模型", updates.get("XBOT_LLM_MODEL", ""))
    table.add_row("微信", wechat)
    console.print(table)
    console.print(
        Panel(
            "[bold]下一步命令[/bold]\n"
            "xbot        [dim]# 进入终端 TUI[/dim]\n"
            "xbot run    [dim]# 启动后端服务和已启用通道[/dim]",
            title="准备完成",
            border_style="cyan",
        )
    )
