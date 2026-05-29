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
tests/                   单元测试和集成测试
.env.example             环境变量示例
```

## 环境要求

- Python 3.11+
- PostgreSQL
- 可选：Redis
- 可选：已登录的 869 服务，用于微信收发消息
- 可选：OpenAI-compatible LLM 服务，用于 Agent

## 快速开始

### 1. 创建虚拟环境

```bat
cd D:\项目\项目\xbot\xbot-next
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -e .[dev]
```

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
XBOT_LLM_BASE_URL=https://api.openai.com/v1
XBOT_LLM_MODEL=gpt-4.1-mini
XBOT_LLM_API_KEY=change-me
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
0.0.0.0:8080
```

检查状态：

```bat
curl http://127.0.0.1:8080/api/v1/system/status
curl http://127.0.0.1:8080/api/v1/adapters
```

### 5. 运行测试

```bat
python -m compileall src tests plugins skills migrations
python -m pytest -q
```

## Agent 使用说明

Agent 由 `plugins/agent_chat` 作为兜底聊天插件接入消息通道。

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

工具调用规则：

- 模型返回 `tool_calls`。
- 后端执行工具。
- 工具结果返回给模型。
- 循环直到模型返回 `final`。
- 工具调用过程不会发送给微信用户，只发送最终回答。

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

## 常用命令

```bat
python -m xbot.cli.main status
python -m xbot.cli.main db-bootstrap
python -m xbot.cli.main db-upgrade
python -m xbot.cli.main db-current
python -m xbot.cli.main run
python -m pytest -q
```

## 相关文档

- [后端框架设计文档](docs/backend-framework-design.md)
