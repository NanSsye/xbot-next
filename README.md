# xbot-next

`xbot-next` 是一个面向 xbot 的新一代后端框架。它不是旧项目的直接搬迁，而是重新设计的模块化、异步优先、可扩展后端。

当前重点是后端能力：

- FastAPI 管理 API
- PostgreSQL 持久化和 Alembic 迁移
- 消息队列、去重、会话和上下文管理
- 插件加载和消息分发
- Skill 加载和执行
- Agent 运行时、工具调用循环、上下文压缩和缓存
- Web 适配器
- 内置 WeChat 869 适配器

## 目录结构

```text
configs/                 默认 TOML 配置
docs/                    设计文档
migrations/              Alembic 数据库迁移
plugins/                 插件目录
skills/                  Skill 目录
src/xbot/                后端源码
ui/                      Web Control UI 前端
tests/                   单元测试和集成测试
.env.example             环境变量示例
.env.local.example       本地简易版环境变量示例
```

## 环境要求

- Python 3.11+
- PostgreSQL
- 可选：Redis
- 可选：已登录的 869 服务，用于微信收发消息
- 可选：OpenAI-compatible LLM 服务，用于 Agent

## 许可协议

本项目采用源码开放的非商业许可：见 [LICENSE](LICENSE)。

- 允许学习、研究、个人非商业使用、修改和非商业分发。
- 禁止未经授权的商业使用，包括销售、SaaS/托管服务、商业集成、付费咨询交付、嵌入商业产品或用于商业经营流程。
- 如需商业使用，请先取得作者书面授权。

注意：由于包含“不可商用”限制，本项目不是 OSI 定义下的开源许可证项目，而是 source-available non-commercial 项目。

## 快速开始

### Docker 本地构建运行

适合普通用户本机部署，不需要单独安装 Python、Node、PostgreSQL 或 Redis。Docker 会直接映射整个项目目录，后续升级可以替换目录文件后重启容器：

```bash
cp .env.example .env
docker compose up -d --build
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

启动后访问：

```text
http://localhost:8548
```

局域网设备访问时使用运行 Docker 的电脑 IP。更多说明见 [Docker 本地构建运行](docs/docker-deployment.md)。

升级时保留 `.env`、`data/`、`logs/`、`workspace/`、`docker-data/`，替换代码后执行：

```bash
docker compose restart xbot
```

### 一键安装

Linux/macOS/WSL：

```bash
curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.sh | bash
```

Windows PowerShell：

```powershell
iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.ps1)
```

如果 GitHub 连接被重置，先给安装器指定代理：

```powershell
$env:XBOT_PROXY="http://127.0.0.1:7897"; iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.ps1)
```

Linux/macOS/WSL：

```bash
XBOT_PROXY="http://127.0.0.1:7897" curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.sh | bash
```

安装器只用于首次安装。它会把项目安装到用户目录，创建 `.venv`、复制 `.env.example` 为 `.env`，生成全局 `xbot` / `xbot-upgrade` 命令，并在首次安装完成后自动进入 `xbot setup` 配置向导：

```bat
xbot setup  # 配置模型、数据库、队列和微信通道
xbot        # 进入终端 TUI
xbot run    # 启动后端服务和通道
xbot-upgrade  # 升级已有安装
```

`xbot setup` 支持两种运行模式：

- 简易版：SQLite + 本地 memory queue，适合个人电脑首次运行，也可以开启 iLink 扫码微信或 869 通道。
- 生产版：PostgreSQL + Redis，适合服务器长期运行，也可以同时开启 iLink 和 869。

非交互默认生成“简易版 + iLink”：

```bat
xbot setup --yes
```

如果安装时想跳过向导：

```bash
XBOT_SKIP_SETUP=1 curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.sh | bash
```

Windows PowerShell：

```powershell
$env:XBOT_SKIP_SETUP="1"; iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/install.ps1)
```

### 单独升级

升级不要再使用安装命令。升级脚本只更新代码和依赖，不初始化配置，不覆盖 `.env`，不删除 `data/`、`logs/`、本地数据库、上传文件和运行期生成的 skill。

已安装过的用户直接运行：

```bat
xbot-upgrade
```

或者：

```bash
curl -fsSL https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/upgrade.sh | bash
```

Windows PowerShell：

```powershell
iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/upgrade.ps1)
```

代理环境：

```powershell
$env:XBOT_PROXY="http://127.0.0.1:7897"; iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/upgrade.ps1)
```

安装目录如果出现本地改动或本地提交与远端分叉，升级器会先创建 `xbot-local-backup-时间戳` 备份分支，并把未提交改动放入 git stash，再把安装目录代码对齐到远端版本；不会执行 `git clean`，所以 `.env` 和未跟踪的运行数据不会被删除。

可选环境变量：

```text
XBOT_INSTALL_DIR    自定义安装目录
XBOT_BIN_DIR        自定义 xbot 命令目录
XBOT_REPO_URL       自定义 Git 仓库地址
XBOT_BRANCH         自定义分支，默认 main
XBOT_PROXY          安装/升级时使用的 HTTP 代理，例如 http://127.0.0.1:7897
```

### 手动开发安装

### 1. 创建虚拟环境

```bat
cd D:\项目\项目\xbot\xbot-next
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -e .[dev]
python -m playwright install chromium
```

说明：`pip install -e .[dev]` 会安装运行所需主依赖、MCP SDK、Playwright SDK 和测试依赖。`playwright install chromium` 用于下载浏览器内核，浏览器截图工具需要它。

### 2. 创建本地配置

复制示例配置：

```bat
copy .env.example .env
```

然后编辑 `.env`。至少需要确认这些项：

```env
XBOT_DATABASE_URL=postgresql+asyncpg://xbot:xbot@192.168.6.19:5433/xbot
XBOT_ADMIN_DATABASE_URL=postgresql://postgres:change-me@192.168.6.19:5433/postgres

XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.openai.com/v1
XBOT_LLM_MODEL=gpt-4.1-mini
XBOT_LLM_CONTEXT_WINDOW_TOKENS=128000
XBOT_LLM_API_KEY=change-me
```

Anthropic 原生接口示例：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=anthropic
XBOT_LLM_BASE_URL=https://api.anthropic.com
XBOT_LLM_MODEL=claude-3-5-sonnet-latest
XBOT_LLM_API_KEY=你的 Anthropic API Key
```

如果要开启微信 869 通道：

```env
XBOT_WECHAT869_ENABLED=true
XBOT_WECHAT869_HOST=192.168.6.19
XBOT_WECHAT869_PORT=5253
XBOT_WECHAT869_WS_URL=ws://192.168.6.19:5253/ws/GetSyncMsg
XBOT_WECHAT869_TOKEN_KEY=你的869 key
XBOT_WECHAT869_BOT_WXID=机器人 wxid
XBOT_WECHAT869_BOT_NICKNAME=机器人昵称
```

`.env` 不会提交到 Git。真实密钥只放本机。

### 3. 初始化数据库

首次运行可以执行：

```bat
python -m xbot.cli.main db-bootstrap
```

只执行迁移：

```bat
python -m xbot.cli.main db-upgrade
```

查看迁移状态：

```bat
python -m xbot.cli.main db-current
```

说明：

- `XBOT_DATABASE_URL` 是应用运行账号。
- `XBOT_ADMIN_DATABASE_URL` 用于创建数据库、授权和执行迁移。
- 如果已有表不是应用账号 owner，迁移会优先使用 admin 连接。

### 4. 启动服务

```bat
python -m xbot.cli.main run
```

默认监听：

```text
0.0.0.0:8548
```

检查状态：

```bat
curl http://127.0.0.1:8548/api/v1/system/status
curl http://127.0.0.1:8548/api/v1/adapters
```

### 5. 运行测试

```bat
python -m compileall src tests plugins skills migrations
python -m pytest -q
```

## Agent 使用说明

Agent 由 `plugins/agent_chat` 作为兜底聊天插件接入消息通道。

## Web Control UI

前端控制台规划见 [docs/frontend-control-ui.md](docs/frontend-control-ui.md)。

第一版 Control UI 使用 Vite + React + TypeScript，视觉风格参考 OpenClaw Control UI：

- 深色控制台布局。
- 左侧导航、顶部状态栏、主内容区。
- “通道”作为一级概念，869、iLink、未来飞书/钉钉/Web 都是通道 adapter。
- 会话页支持查看通道会话历史，并在页面内和 Agent 对话。
- 页面内对话默认只显示在控制台，不回发到原通道。
- 工具调用、后台任务和 Agent 事件通过活动流展示。

开发运行：

```powershell
cd ui
npm install
npm run dev
```

生产构建并随后端托管：

```powershell
xbot ui-build
xbot run
```

生产环境必须给 Control UI/API 开启访问令牌：

```env
XBOT_API_AUTH_ENABLED=true
XBOT_API_TOKEN=请替换为足够长的随机值
```

处理规则：

- 私聊文本消息会直接进入 Agent。
- 群聊文本消息只有提到机器人时才进入 Agent。
- Agent 会收到当前消息的结构化上下文，包括：
  - `scope`
  - `conversation_id`
  - `sender_id`
  - `sender_wxid`
  - `sender_name`
  - `private_wxid`
  - `group_wxid`
  - `group_member_wxid`
  - 最近会话消息
  - 会话摘要

Agent 可用工具包括：

- `filesystem.read_file`
- `filesystem.write_file`
- `filesystem.list_dir`
- `filesystem.delete_path`
- `shell.exec`
- `skill.list`
- `skill.describe`
- `skill.run`
- `environment.snapshot`
- `environment.which`
- `environment.ports`
- `task.start`
- `task.status`
- `task.list`
- `task.cancel`
- `browser.screenshot_url`
- `browser.run_actions`
- `browser.session_open`
- `browser.session_actions`
- `browser.session_list`
- `browser.session_close`
- `database.query`
- `database.schema`
- `git.status`
- `git.log`
- `git.diff`
- `github.repo_info`
- `github.issue_list`
- `github.issue_view`
- `github.issue_create`
- `github.pr_list`
- `github.pr_view`
- `github.pr_comment`
- `github.graphql`
- `github.workflow_list`
- `github.run_list`
- `github.run_view`
- `github.run_logs`
- `github.run_rerun`

插件也可以通过两种方式暴露 Agent 工具：

- 在插件类里实现 `agent_tools()`，返回 `ToolDefinition`。
- 在 `plugin.toml` 中声明 `[[agent_tools]]`，并绑定插件方法名。

示例：

```toml
[[agent_tools]]
name = "plugin.my_tool"
handler = "my_tool"
description = "Run my plugin tool."
risk_level = "read"
toolset = "plugin"
platforms = ["wechat"]
scopes = ["private", "group"]
modes = ["developer", "admin"]
```

插件工具权限/可见性查询：

- `GET /api/v1/plugins/agent-tools`
- `GET /api/v1/plugins/{name}/agent-tools`
- `GET /api/v1/agent/tools/visibility`
- `POST /api/v1/agent/background-tasks`
- `GET /api/v1/agent/background-tasks/overview`
- `GET /api/v1/agent/background-tasks`
- `GET /api/v1/agent/background-tasks/{task_id}`
- `POST /api/v1/agent/background-tasks/{task_id}/replay`
- `POST /api/v1/agent/background-tasks/{task_id}/cancel`

工具调用规则：

- 模型返回 `tool_calls`。
- 后端执行工具。
- 工具结果返回给模型。
- 循环直到模型返回 `final`。
- 工具调用过程不会发送给微信用户，只发送最终回答。
- 长任务可以通过 `task.start` 后台执行；如果带有通道通知信息，完成后会主动回发原会话。
- 定时任务可以通过 `schedule.create` 创建；支持 `30m`、`every 2h`、`daily 09:00`、ISO 时间和 5 段 cron。通道来源创建的任务会保存原平台、adapter、会话和引用消息，后续结果按原通道路由。
- 工具失败会返回结构化 `error_type` 和 `fallback`，只读 fallback 会自动尝试一次安全降级。
- 浏览器、GitHub Actions logs、`skill.run` 等长任务工具会在 metadata 中标记 `background_candidate`。
- 服务重启后会恢复后台任务记录；未完成且可重放的只读后台任务会安全重放一次。
- 通道来源中调用 `background_candidate` 工具时，Agent 会自动改为后台任务并在完成后回发。

定时任务 CLI：

```powershell
xbot schedule list
xbot schedule add "every 2h" "检查项目状态并总结"
xbot schedule pause JOB_ID
xbot schedule resume JOB_ID
xbot schedule run JOB_ID
xbot schedule delete JOB_ID
```

## 权限配置

默认是 developer 模式：

```env
XBOT_AGENT_MODE=developer
XBOT_AGENT_ALLOW_SHELL=false
XBOT_AGENT_ALLOW_FILE_WRITE=true
XBOT_AGENT_WORKSPACE_ROOT=.
XBOT_AGENT_WORKSPACE_ROOTS=.
```

如果要允许 `skill.run` 或 shell 命令：

```env
XBOT_AGENT_ALLOW_SHELL=true
```

如果要启用 admin 模式：

```env
XBOT_AGENT_ADMIN_MODE_ALLOWED=true
XBOT_AGENT_MODE=admin
```

生产环境不建议开启 admin 模式。

## 缓存和上下文

Agent 当前有两类缓存：

- 静态 prompt 片段缓存：提高工具和 skills 描述的复用命中。
- 只读工具结果 TTL 缓存：短时间内重复读取文件、目录、skill 信息时复用结果。

相关配置：

```env
XBOT_AGENT_CACHE_ENABLED=true
XBOT_AGENT_CACHE_TOOL_RESULT_TTL_SECONDS=30
XBOT_AGENT_CACHE_STATIC_PROMPT=true
XBOT_AGENT_CACHE_TOOL_RESULTS=true
XBOT_AGENT_CACHE_SKILLS=true
```

会话上下文默认读取全量历史，并在达到阈值后自动摘要：

```toml
[conversation.context]
recent_messages = 0
max_chars = 16000
auto_summarize = true
summary_every_messages = 50
```

## Skill 使用

Skill 放在 `skills/` 目录下，每个 skill 通常包含：

```text
skill.toml
SKILL.md
脚本文件
```

当前内置微信发送 skill：

```text
skills/微信发送skill
```

真实 869 配置文件：

```text
skills/微信发送skill/wechat-869.json
```

该文件包含真实地址和 key，已被 `.gitignore` 忽略，不会提交。

## MCP 使用

`xbot-next` 内置原生 MCP client。启动时会连接配置的 MCP servers，自动发现工具，并注册成 Agent 可调用的一等工具。

MCP 工具命名规则：

```text
mcp_{server_name}_{tool_name}
```

例如：

```text
mcp_time_get_current_time
mcp_filesystem_read_file
mcp_github_list_issues
```

### 配置 stdio MCP server

在 `configs/xbot.toml` 中添加：

```toml
[agent.mcp]
enabled = true

[agent.mcp.servers.time]
command = "uvx"
args = ["mcp-server-time"]
timeout = 120
connect_timeout = 60
```

### 配置 HTTP MCP server

```toml
[agent.mcp.servers.company_api]
url = "https://mcp.example.com/mcp"
timeout = 180
connect_timeout = 60

[agent.mcp.servers.company_api.headers]
Authorization = "Bearer change-me"
```

### 安全说明

stdio MCP server 不会继承完整系统环境变量，只会继承基础安全环境变量。需要传给 MCP server 的 token 或 key 必须显式写到 server 的 `env` 配置里：

```toml
[agent.mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]

[agent.mcp.servers.github.env]
GITHUB_PERSONAL_ACCESS_TOKEN = "change-me"
```

## 常用命令

```bat
python -m xbot.cli.main status
python -m xbot.cli.main db-bootstrap
python -m xbot.cli.main db-upgrade
python -m xbot.cli.main db-current
python -m xbot.cli.main run
python -m xbot.cli.main chat
python -m pytest -q
```

## 终端 Agent 对话

不经过微信通道时，可以直接在终端里和 Agent 对话：

```bat
xbot
python -m xbot.cli.main chat
```

可选参数：

```bat
xbot chat --tui
python -m xbot.cli.main chat --session dev-1 --cwd D:\项目\项目\xbot\xbot-next
python -m xbot.cli.main chat --verbose
python -m xbot.cli.main chat --fancy-input
python -m xbot.cli.main chat --tui
python -m xbot.cli.main chat-bridge
```

终端模式默认使用 Windows 原生输入，中文输入法兼容性最好；需要命令补全、本地输入历史、多行输入和底部状态栏时，可以加 `--fancy-input` 启用 `prompt_toolkit`。`--fancy-input` 使用 `patch_stdout` 保护输入区，避免后台输出覆盖正在输入的内容。
启动时会先显示启动 spinner，随后展示接近 Hermes CLI 的首页：左侧品牌 ASCII、ready 状态、模型和会话信息，右侧按 toolset/skill 展示可用能力，底部显示欢迎语和输入提示。
Agent 执行过程中默认使用 Hermes 风格的轻量 CLI 对话：用户输入显示为 prompt 行，自然语言回复会在 `xbot` 标题块里流式显示，工具调用 JSON 会被隐藏；本轮结束后显示模型、上下文占用、百分比进度条、本轮耗时和 LLM 耗时。上下文已用量优先读取 OpenAI-compatible usage，窗口总量优先读取 `XBOT_LLM_CONTEXT_WINDOW_TOKENS` / `agent.llm.context_window_tokens`，未配置时按常见模型兜底估算。`--verbose` 会额外显示工具输入摘要和 activity 明细，`--debug` 会额外显示工具输出摘要。终端保持打开时，后台任务完成、失败或取消也会主动打印提示。
执行中按 `Ctrl+C` 会尝试取消当前终端任务，并保留终端会话。
当前终端会话会保留最近的 Agent 事件和后台任务事件，方便事后用命令回看，不需要翻滚动日志。
终端对话模式会把框架运行日志写入 `logs/xbot-terminal.log`，避免 INFO 日志刷屏污染对话区；`--debug` 会重新把调试日志输出到控制台。
`--tui` 会进入 Textual 全屏终端界面，左侧显示对话，右侧显示工具事件和后台任务事件，底部输入框继续复用同一套 slash command。
`chat-bridge` 是 JSONL stdin/stdout 协议入口，用于后续独立 TUI/Web/PTY 前端进程接入同一套 AgentRuntime。
安装为可编辑包后，`xbot` 不带子命令会进入普通终端对话模式，中文输入兼容性更好；`xbot chat --fancy-input` 用于启用补全/历史；`xbot chat --tui` 用于进入全屏 TUI；`xbot run` 仍用于启动后端服务。

内置命令：

```text
/help       查看命令
/exit       退出
/status     查看 runtime、LLM、MCP 状态
/tools      查看当前终端可见工具
/tasks      查看后台任务
/task ID    查看后台任务详情
/replay ID  重放失败后台任务
/events N   查看最近 N 条 Agent 工具/LLM/task 事件
/logs N     同时查看最近 N 条 Agent 事件和后台任务事件
/new        开启新的终端会话
```

## 相关文档

- [后端框架设计文档](docs/backend-framework-design.md)
- [Web Control UI 设计文档](docs/frontend-control-ui.md)
- [生产部署清单](docs/production-deployment.md)
