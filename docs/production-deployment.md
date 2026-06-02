# 生产部署清单

这份清单面向长期运行的 xbot 实例。个人电脑试用可以使用 SQLite + memory queue；面向真实用户或团队时建议按下面方式部署。

更新时间：2026-06-02

## 基础拓扑

- xbot 后端：`xbot run`，默认 `0.0.0.0:8548`。
- Control UI：执行 `xbot ui-build` 后由后端同源托管 `/`。
- 数据库：PostgreSQL，保存会话、消息、Agent 任务、定时任务和运行事件。
- Hermes 数据：`data/hermes/`，保存 Agent 会话、记忆、skills、自进化和轨迹。
- 队列：Redis，用于消息队列和后续横向扩展。
- 反向代理：Nginx、Caddy 或同类网关，负责 HTTPS、域名和访问日志。

## 必须配置

```env
XBOT_API_AUTH_ENABLED=true
XBOT_API_TOKEN=请替换为足够长的随机值

XBOT_STORAGE_TYPE=postgresql
XBOT_DATABASE_URL=postgresql+asyncpg://xbot:强密码@127.0.0.1:5432/xbot
XBOT_ADMIN_DATABASE_URL=postgresql://postgres:管理员密码@127.0.0.1:5432/postgres
XBOT_DATABASE_AUTO_BOOTSTRAP=true
XBOT_DATABASE_RUN_MIGRATIONS_ON_STARTUP=true

XBOT_QUEUE_TYPE=redis
XBOT_REDIS_URL=redis://127.0.0.1:6379/15

XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.openai.com/v1
XBOT_LLM_MODEL=gpt-4.1-mini
XBOT_LLM_API_KEY=你的模型密钥
```

Anthropic 原生接口可改为：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=anthropic
XBOT_LLM_BASE_URL=https://api.anthropic.com
XBOT_LLM_MODEL=claude-3-5-sonnet-latest
XBOT_LLM_API_KEY=你的 Anthropic API Key
```

MiniMax Anthropic 兼容接口可改为：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=anthropic
XBOT_LLM_BASE_URL=https://api.minimaxi.com/anthropic
XBOT_LLM_MODEL=MiniMax-M3
XBOT_LLM_API_KEY=你的 MiniMax API Key
```

多模态、工具调用、记忆和 skill 自进化由 Hermes 负责。xbot 通道层会把已下载附件路径交给 Hermes，是否能理解图片/视频取决于当前 Hermes 模型和工具能力。

如果 Control UI 和 API 不同源，额外配置：

```env
XBOT_API_CORS_ORIGINS=https://console.example.com
```

## 权限建议

- `XBOT_AGENT_MODE=developer`：默认建议值。
- `XBOT_AGENT_ALLOW_SHELL=false`：生产默认关闭 shell。
- `XBOT_AGENT_MAX_TOOL_ITERATIONS=0`：默认不限制单轮工具循环，适合长任务；重复后台任务由 runtime 单独收口。
- `XBOT_AGENT_AUTO_DELEGATE_CHANNEL_TASKS=true`：通道里的复杂开发任务自动交给后台子 Agent 持续完成，完成后回发。
- 不建议生产环境启用 `XBOT_AGENT_MODE=admin`。
- 不把 `.env`、`data/`、`logs/`、用户上传文件和通道媒体目录提交到 Git。

## 通道数据

通道消息统一进入会话系统，不按每个群或用户单独建表，而是通过 `conversation_id` 区分：

- 私聊：一个私聊一个 conversation。
- 群聊：一个群一个 conversation。
- 不同 adapter 的会话 ID 带 platform/adapter 前缀，避免串号。

文件和图片按通道分目录保存，例如：

- `data/wechat869/media`
- `data/wechat_ilink/media`

生产环境需要把 `data/` 纳入备份。

## 869 通道

869 通道生产建议：

```env
XBOT_WECHAT869_ENABLED=true
XBOT_WECHAT869_HOST=192.168.6.19
XBOT_WECHAT869_PORT=5253
XBOT_WECHAT869_ADMIN_KEY=你的admin key
XBOT_WECHAT869_TOKEN_KEY=固定token key
XBOT_WECHAT869_DEVICE_TYPE=ipad
XBOT_WECHAT869_MEDIA_ENABLED=true
XBOT_WECHAT869_TEXT_ONLY=false
```

规则：

- `.env` 中的 `XBOT_WECHAT869_TOKEN_KEY` 优先级最高，数据库里的运行态 token 不覆盖它。
- 如果 `.env` 没有 token key，系统可以使用数据库中保存的 token/poll/auth key 恢复登录态。
- 如果没有 token key，但配置了 admin key，前端可以用 admin key 获取或生成 auth key，再获取二维码。
- 重启后会调用 869 登录状态和 profile 接口刷新 Bot wxid / Bot 昵称。
- 869 的 `/user/GetProfile` 可能返回 `Code=200`、`Success=false`，但 `Data.userInfo` 仍然有效，系统按 `Code=200 + Data.userInfo` 解析。

前端通道卡片会显示 Host、Port、WebSocket、Admin Key、Token Key、Auth Key、Poll Key、Bot wxid、Bot 昵称、设备类型和登录状态。生产公网环境必须保护 Control UI，不要裸露这些字段。

## 页面配置持久化

Control UI 中的开关分两类：

- 通道开关：写入数据库 `adapter_states.state_json.enabled`。`.env` / `configs/xbot.toml` 是默认值，页面覆盖值优先生效，服务重启后仍会按页面最后设置恢复。
- 插件和 Skill 开关：写入 `plugins.enabled` / `skills.enabled`，重启和升级后继续生效。

页面开关只保存启用状态。通道 host、token、模型 key、数据库连接等敏感配置仍建议放在 `.env` 或后续专门的密钥管理里，不直接写入前端可见配置。

## Redis 队列稳定性

生产环境使用 Redis Streams：

- 发布消息时会确保 consumer group 存在。
- 消费端使用 consumer group + ack。
- 消费协程异常后不会直接退出，会记录日志并重试。
- Runtime 会监控 MessageConsumer 任务，如果任务异常退出，会自动重启。
- 未 ack 的 pending 消息会在空闲一段时间后通过 `XAUTOCLAIM` 重新领取，避免“消息进 Redis 但必须重启才处理”。

Redis 连接的读超时必须大于 `XREADGROUP block` 等待时间。当前实现会按 `block_ms + 10 秒` 设置 `socket_timeout`，避免空队列等待被误判为：

```text
Timeout reading from <redis-host>:6379
```

如果仍然持续出现 Redis timeout，优先检查：

- Redis 服务是否稳定。
- xbot 到 Redis 的网络是否丢包。
- Redis 是否被防火墙或代理中断长连接。
- 是否多个实例使用了相同 consumer name 导致 pending 行为混乱。

## 升级

已安装用户使用：

```powershell
xbot-upgrade
```

或：

```powershell
iex (irm https://raw.githubusercontent.com/NanSsye/xbot-next/main/scripts/upgrade.ps1)
```

升级器只更新代码和依赖，不覆盖 `.env`，不删除 `data/`、`logs/`、本地数据库、上传文件和运行期生成的 skill。

## 备份

建议至少备份：

- PostgreSQL 数据库。
- `.env`。
- `data/`。
- 自定义 `plugins/`。
- 自定义 `skills/`。
- 反向代理配置。

## 上线验证

```powershell
xbot ui-build
xbot run
curl http://127.0.0.1:8548/api/v1/system/status
```

启用 API token 后：

```powershell
curl -H "Authorization: Bearer 你的token" http://127.0.0.1:8548/api/v1/system/status
```

浏览器访问后端根路径，输入 `XBOT_API_TOKEN`，确认：

- 总览状态正常。
- 通道状态正常。
- 对话页能加载会话。
- WebSocket 活动流能收到 `ui.connected`。
- 页面内 Agent 对话不会默认回发原通道。
