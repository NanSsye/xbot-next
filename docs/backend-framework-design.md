# xbot 后端框架设计

更新时间：2026-06-02

## 当前定位

xbot 后端保留消息框架、通道适配器、插件路由、API、任务记录、后台任务和 Web 控制台。

Agent 执行不再使用 xbot 自研规划循环。所有 Agent 对话、上下文恢复、记忆、工具循环、轨迹、skill 自进化和 curator 生命周期由内嵌 Hermes 负责。

```text
通道消息
  -> xbot adapter
  -> xbot runtime queue
  -> 普通插件
  -> fallback 插件 agent_chat
  -> xbot AgentRuntime wrapper
  -> vendor/hermes/run_agent.py::AIAgent
```

## 职责边界

xbot 负责：

- 微信、Web、终端等通道接入。
- 插件加载、启停、路由和 `exclusive` 阻断。
- `agent_chat` fallback 触发条件。
- Agent task/event/artifact/background/schedule 记录。
- Web/API 控制台。
- Docker、本地安装和生产部署入口。

Hermes 负责：

- Agent 主循环。
- 会话历史恢复和压缩。
- memory/user profile。
- 工具调用和工具错误恢复。
- Hermes skills。
- 自进化和 curator。
- trajectory 保存。
- Hermes 扩展环境变量。

## 持久化

框架数据：

```text
data/
logs/
workspace/
```

Hermes 数据：

```text
data/hermes/config.yaml
data/hermes/.env
data/hermes/sessions/
data/hermes/memories/
data/hermes/skills/
data/hermes/logs/
```

Docker 和本地生产部署都应持久化整个项目目录，至少要持久化 `data/`、`logs/`、`workspace/` 和根目录 `.env`。

## Agent API

保留的 xbot Agent 控制面只负责任务和观测：

- `POST /api/v1/agent/tasks`
- `GET /api/v1/agent/tasks`
- `GET /api/v1/agent/tasks/{task_id}`
- `POST /api/v1/agent/tasks/{task_id}/resume`
- `GET /api/v1/agent/events`
- `GET /api/v1/agent/background-tasks`
- `GET /api/v1/agent/background-tasks/overview`
- `GET /api/v1/agent/background-tasks/{task_id}`
- `POST /api/v1/agent/background-tasks/{task_id}/replay`
- `POST /api/v1/agent/background-tasks/{task_id}/cancel`
- `GET /api/v1/agent/scheduled-jobs`
- `POST /api/v1/agent/scheduled-jobs`

已移除的旧自研 Agent 控制面：

- `/api/v1/agent/memory/*`
- `/api/v1/agent/memories/*`
- `/api/v1/agent/wiki/*`
- `/api/v1/agent/curator/*`
- `/api/v1/agent/skills/agent-owned`

这些能力现在属于 Hermes。后续如果要做管理页，应读取 Hermes 自己的数据结构或调用 Hermes 提供的管理能力，而不是恢复 xbot 旧实现。

## 配置

主模型仍统一使用根目录 `.env`：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.example.com/v1
XBOT_LLM_MODEL=MiniMax-M3
XBOT_LLM_API_KEY=change-me
```

Hermes 专属扩展 key 放到：

```text
data/hermes/.env
```

旧变量不再控制 Agent 执行：

```text
XBOT_AGENT_TOOLSETS_*
XBOT_AGENT_CACHE_*
XBOT_AGENT_MEMORY_COMPACTION_*
XBOT_AGENT_WORKSPACE_*
XBOT_AGENT_MCP_ENABLED
XBOT_LLM_MULTIMODAL_*
```

## 插件路由

普通插件优先于 `agent_chat` 运行。

`plugin.toml` 中 `exclusive = true` 的插件只要路由命中，就会阻断后续 fallback。OpenClaw 桥这类插件应使用该模式，避免消息同时进入 Hermes。

机器人自身发送的消息必须在 adapter 或插件层过滤，不能重新进入 xbot runtime，否则会造成自唤醒。

## 后续优化

- 为 Hermes memory、sessions、skills、trajectory 做只读管理页。
- 给 Hermes task/event 流增加更完整的前端实时展示。
- 补充 Hermes 配置导入/导出和生产环境诊断。
- 对 `vendor/hermes` 更新流程做脚本化，便于以后直接替换源码。
