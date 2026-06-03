# xbot 后端框架设计

更新时间：2026-06-03

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
- 869 通道的管理员/普通成员/访客权限分级，以及普通成员工具调用前的硬策略拦截。
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

## 869 Agent 权限模型

869 通道按触发消息的 wxid 分为三档：

```text
admin   完整 Hermes 工具权限
member  受限工具权限，可在授权目录内读写文件、写代码、使用公网搜索
guest   只聊天，不调用工具
```

权限只影响当前消息的工具能力，不拆分 Hermes 会话。也就是说同一个微信群始终映射到同一个 Hermes session，群里的管理员和普通成员共享群会话记忆；xbot 只在每次工具调用前按当前触发者权限做硬拦截。

普通成员默认允许：

- 公网搜索和公开网页读取。
- 授权目录内的文件读取、写入、搜索和补丁。
- 授权目录内的终端开发命令。
- Hermes memory、todo、skills 查看/管理等低风险能力。

普通成员默认禁止：

- 访问 `localhost`、内网 IP、私有网段和 `.local` 主机。
- 扫描网段或探测同网段设备，例如 `nmap`、`masscan`、`arp -a`、`net view`、`ipconfig /all`、`Test-NetConnection` 等。
- 读取或写入授权目录外的文件。
- `execute_code`、`delegate_task`、`cronjob`、`process`、主动 `send_message`、浏览器控制、智能家居控制等高风险工具。

授权目录通过 `.env` 设置：

```env
XBOT_AGENT_MEMBER_POLICY_ENABLED=true
XBOT_AGENT_MEMBER_WORKSPACE_ROOTS=workspace,.agent-workspace
XBOT_AGENT_MEMBER_ALLOW_TERMINAL=true
XBOT_AGENT_MEMBER_ALLOW_PUBLIC_WEB=true
XBOT_AGENT_MEMBER_BLOCK_PRIVATE_NETWORK=true
```

`XBOT_AGENT_MEMBER_WORKSPACE_ROOTS` 支持多个目录，用英文逗号分隔。相对路径按 xbot 启动时的项目根目录解析；绝对路径可以直接写 Windows 路径，例如：

```env
XBOT_AGENT_MEMBER_WORKSPACE_ROOTS=workspace,D:\projects\allowed,C:\Users\Administrator\Desktop\agent-work
```

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
