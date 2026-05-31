# Web Control UI

`xbot-next` 的 Web Control UI 是给本地或服务器运行实例使用的控制台，不是营销站点。第一版目标是把通道、会话、Agent 运行、工具调用、后台任务和定时任务放到一个实时界面里。

## 目标

- 统一管理“通道”，不把概念限定为微信。869、iLink、Web、飞书、钉钉等后续都作为 adapter 接入。
- 选择任意通道会话，查看本地保存的历史消息、摘要和上下文状态。
- 在页面内直接和 Agent 对话，默认只显示在控制台，不回发原通道。
- 在需要时显式选择“回发通道”，由 Agent 按当前通道上下文调用受控发送工具。
- 展示 Agent 的 LLM 调用、工具调用、后台任务、定时任务运行结果等活动明细。
- 为后续插件、Skill、模型和权限配置提供统一入口。

## 技术栈

- Vite + React + TypeScript。
- 原生 CSS variables 作为第一版设计系统，避免过早引入复杂 UI 框架。
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

## 页面规划

- 对话：选择通道会话、查看历史消息、页面内和 Agent 对话、查看当前活动。
- 总览：后端状态、通道数量、后台任务数量、定时任务数量。
- Agent：查看 LLM/MCP 状态、重载 MCP、搜索工具、添加/删除/压缩长期记忆。
- 通道：展示 adapter 平台、启用状态和运行状态；页面开关写入数据库，重启后继续生效。
- 插件 / Skills：启用、停用和重载；状态写入数据库。
- 后台任务：查看后台任务状态、来源、结果和错误；支持取消运行中任务和重放可重放任务。
- 定时任务：创建任务，查看计划、时区、下次运行、启用状态；支持暂停、恢复、立即运行和删除。
- 活动流：集中展示 Agent 事件、工具调用和 WebSocket 实时事件。
- 设置：管理浏览器本地保存的 API Token，查看 REST 和 WebSocket 端点。

## 本地开发

```powershell
cd ui
npm install
npm run dev
```

Vite 默认监听 `5173`，并把 `/api` 代理到 `http://127.0.0.1:8080`。

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
