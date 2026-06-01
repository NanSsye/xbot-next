# Web Control UI

`xbot-next` 的 Web Control UI 是给本地或服务器运行实例使用的控制台，不是营销站点。第一版目标是把通道、会话、Agent 运行、工具调用、后台任务和定时任务放到一个实时界面里。

更新时间：2026-06-01

## 目标

- 统一管理“通道”，不把概念限定为微信。869、iLink、Web、飞书、钉钉等后续都作为 adapter 接入。
- 选择任意通道会话，查看本地保存的历史消息、摘要和上下文状态。
- 在页面内直接和 Agent 对话，默认只显示在控制台，不回发原通道。
- 在需要时显式选择“回发通道”，由 Agent 按当前通道上下文调用受控发送工具。
- 展示 Agent 的 LLM 调用、工具调用、后台任务、定时任务运行结果等活动明细。
- 为后续插件、Skill、模型和权限配置提供统一入口。

## 技术栈

- Vite + React + TypeScript。
- shadcn 默认风格方向 + 原生 CSS variables 作为第一版设计系统。
- lucide-react 用于控制台常用图标。
- REST 用于状态、列表、CRUD 和一次性查询。
- WebSocket 用于实时事件流。

## 视觉方向

界面参考 OpenClaw Control UI 的工作台风格：

- 深色控制台。
- 左侧主导航。
- 顶部状态栏。
- 中间主工作区。
- 右侧活动流。
- 高密度信息展示，优先服务日常运维和 Agent 调试。

第一版不做 landing page，不使用大 hero、装饰性渐变、宣传卡片。控制台打开后直接进入可用的对话工作区。

## 数据流

### REST

- `GET /api/v1/system/status`
- `GET /api/v1/adapters`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{id}/messages`
- `DELETE /api/v1/conversations/{id}`
- `POST /api/v1/agent/tasks`
- `GET /api/v1/agent/tasks`
- `GET /api/v1/agent/tasks/{task_id}`
- `POST /api/v1/agent/tasks/{task_id}/resume`
- `GET /api/v1/agent/events`
- `GET /api/v1/agent/background-tasks`
- `GET /api/v1/agent/scheduled-jobs`

### WebSocket

- `WS /api/v1/events/ws`

事件类型先保持通用：

- `ui.connected`
- `agent.event`
- `background_task.updated`

后续可以继续扩展 `conversation.updated`、`adapter.status_changed`、`scheduled_job.updated` 等事件。

## 对话模式

### 控制台模式

默认模式。用户在 Web 页面输入消息后：

1. 前端把当前选中的通道会话作为上下文附加给 Agent。
2. 后端以 `terminal:control-ui` 作为 source 运行 Agent。
3. Agent 回复只显示在 Web 页面。
4. 不自动发送到微信、飞书或其他原始通道。

这个模式适合调试、查看上下文、让 Agent 根据某个通道会话做分析，但不打扰真实聊天。

### 回发通道模式

用户显式切换到“回发通道”后，前端会把 `delivery_mode: channel` 放入任务上下文。是否真正回发由 Agent 的工具权限、当前通道能力和后端策略共同决定。

第一版仍然保持保守：页面本身不直接调用 adapter 发送消息，避免绕过 Agent 工具审计。

## 已落地页面

- 对话：选择通道会话、查看历史消息、页面内和 Agent 对话、查看当前活动。
- 总览：后端状态、通道数量、后台任务数量、定时任务数量。
- Agent：查看 LLM/MCP 状态、重载 MCP、搜索工具、添加/删除/压缩长期记忆。
- 任务：查看 Agent 任务列表、任务详情、工具调用流、时间线和失败修复建议。
- 通道：每个 adapter 一张卡片，展示配置启用、页面覆盖、实际启用、运行中、登录支持和运行参数。
- 扩展：插件和 Skill 单独管理，不混在通道页；支持启用、停用、重载和状态查看。
- 后台任务：查看后台任务状态、来源、结果和错误；支持取消运行中任务和重放可重放任务。
- 定时任务：创建任务，查看计划、时区、下次运行、启用状态；支持暂停、恢复、立即运行和删除。
- 活动流：集中展示 Agent 事件、工具调用和 WebSocket 实时事件。
- 设置：管理浏览器本地保存的 API Token，查看 REST 和 WebSocket 端点。

## 任务轨迹

任务页基于后端 `agent_events` 做结构化投影，不额外要求新表迁移：

- `task`：任务输入、输出、状态、来源和时间。
- `timeline`：按事件顺序展示 LLM、工具、任务生命周期。
- `tool_calls`：聚合 `tool.started`、`tool.completed`、`tool.failed`、`tool.denied` 等事件，显示输入、输出、错误和 fallback。
- `repairs`：从失败工具的 fallback 中提取 `guidance`、`repair_steps`、`suggested_tool` 和 `suggested_payload`，方便定位为什么失败、下一步怎么修。
- `artifacts`：展示工具登记的文件、skill 产物和大工具结果落盘路径。

WebSocket 收到 `agent.event` 后会实时追加活动流；如果当前打开的是该任务详情，会自动刷新工具流和时间线。
任务详情页提供“继续”按钮，会调用 resume API，让 Agent 带着原任务轨迹在同一个 `task_id` 上原地续跑；续跑完成后原任务结果会更新。

## 通道页

通道页不使用“微信通道”作为一级概念，统一叫“通道”。微信 869、微信 iLink、Web、飞书、钉钉等都只是不同 adapter。

每张通道卡片包含：

- adapter 名称、平台、运行状态。
- 配置启用：来自 `.env` / `configs/xbot.toml` 的默认启用状态。
- 页面覆盖：Control UI 写入数据库后的覆盖状态。
- 实际启用：运行时最终采用的启用状态。
- 运行中：adapter 是否已经启动。
- 登录支持：当前 adapter 是否提供登录流程。
- 操作：启用/停用通道、获取二维码、检查登录。

### 869 登录展示

869 通道卡片显示：

- Host / Port。
- WebSocket URL。
- Admin Key。
- Token Key。
- Auth Key。
- Poll Key。
- Bot wxid。
- Bot 昵称。
- 设备类型。
- 设备 ID。
- 媒体开关。
- 仅文本开关。
- 登录状态。

这些字段允许直接显示，不做掩码，方便本地部署排查。生产公网部署时必须用 API Token、HTTPS 和反向代理访问控制保护 Control UI。

869 登录流程：

1. 如果 `.env` 已配置 `XBOT_WECHAT869_TOKEN_KEY`，优先使用固定 token key。
2. 如果没有 token key，但有持久化的 DB token/poll/auth key，则从数据库恢复。
3. 如果还没有可用 token，则用 admin key 获取或生成 auth key。
4. 点击“获取二维码”后，用 auth/token key 请求 869 登录二维码。
5. 扫码后点击“检查登录”，前端会刷新登录状态、token、poll key、Bot wxid 和 Bot 昵称。
6. 服务重启后会自动读取 `.env` 和数据库状态，并通过 869 profile/status 接口刷新资料；已经登录的场景不需要重复扫码。

当前 869 profile 兼容 `Code=200` 且 `Success=false` 但 `Data.userInfo` 有效的返回。Bot wxid 从 `Data.userInfo.userName.str` 解析，昵称从 `Data.userInfo.nickName.str` 解析。

### iLink 登录展示

iLink 通道卡片也保留登录入口和二维码展示。后续如果协议提供更多登录态字段，需要按相同卡片结构补充，而不是把配置散落到其他页面。

## 扩展页

插件和 Skill 单独放在“扩展”页面：

- 插件：展示名称、版本、启用状态、描述和来源。
- Skill：展示名称、启用状态、描述和来源。
- 页面开关写入数据库，重启后保留。
- 插件和 Skill 的安装、升级、删除后续可以继续在这里扩展。

通道页只负责 adapter；扩展页只负责插件和 Skill。不要再把两类概念混在同一张通道卡片里。

## 配置持久化

Control UI 的开关不是只存在浏览器里：

- 通道启用状态写入 `adapter_states.state_json.enabled`。
- 插件启用状态写入插件仓储。
- Skill 启用状态写入 Skill 仓储。
- 登录态、运行态 token、poll key、bot wxid、bot nickname 写入 adapter state。

`.env` 仍然是敏感固定配置的首选来源，例如数据库、Redis、模型密钥、869 admin key 和固定 token key。数据库状态不能覆盖 `.env` 里的固定 token key。

## 本地开发

```powershell
cd ui
npm install
npm run dev
```

Vite 默认监听 `5173`，并把 `/api` 代理到 `http://127.0.0.1:8548`。

生产构建：

```powershell
xbot ui-build
```

当 `ui/dist` 存在时，后端会把前端静态文件挂载到 `/`。

## 生产安全

Control UI 能读取会话、执行 Agent 任务、查看工具调用和后台任务，因此生产环境必须开启 API Token：

```env
XBOT_API_AUTH_ENABLED=true
XBOT_API_TOKEN=请替换为足够长的随机值
```

页面首次访问受保护后端时会提示输入 `XBOT_API_TOKEN`。Token 只保存在当前浏览器的 localStorage。REST 请求会使用 Bearer token，WebSocket 事件流会在连接参数中携带 token。

如果前端与后端不同源部署，需要配置 CORS：

```env
XBOT_API_CORS_ORIGINS=https://console.example.com,http://127.0.0.1:5173
```

推荐生产部署方式：

1. 后端和 `ui/dist` 同源部署，由 xbot 后端直接托管 Control UI。
2. 使用反向代理启用 HTTPS。
3. 开启 `XBOT_API_AUTH_ENABLED=true`。
4. `XBOT_AGENT_MODE` 保持 `developer` 或 `safe`，不要在生产环境随意开启 admin 模式。
5. PostgreSQL + Redis 用于长期运行；SQLite + memory queue 只作为个人简易版。
