# 生产部署清单

这份清单面向长期运行的 xbot 实例。个人电脑试用可以使用 SQLite + memory queue；面向真实用户或团队时建议按下面方式部署。

## 基础拓扑

- xbot 后端：`xbot run`，默认 `0.0.0.0:8080`。
- Control UI：执行 `xbot ui-build` 后由后端同源托管 `/`。
- 数据库：PostgreSQL，保存会话、消息、Agent 任务、记忆、定时任务和运行事件。
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
XBOT_LLM_BASE_URL=https://api.openai.com/v1
XBOT_LLM_MODEL=gpt-4.1-mini
XBOT_LLM_API_KEY=你的模型密钥
```

如果 Control UI 和 API 不同源，额外配置：

```env
XBOT_API_CORS_ORIGINS=https://console.example.com
```

## 权限建议

- `XBOT_AGENT_MODE=developer`：默认建议值。
- `XBOT_AGENT_ALLOW_SHELL=false`：生产默认关闭 shell。
- `XBOT_AGENT_WORKSPACE_ROOTS` 只配置需要 Agent 访问的业务目录。
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

## 页面配置持久化

Control UI 中的开关分两类：

- 通道开关：写入数据库 `adapter_states.state_json.enabled`。`.env` / `configs/xbot.toml` 是默认值，页面覆盖值优先生效，服务重启后仍会按页面最后设置恢复。
- 插件和 Skill 开关：写入 `plugins.enabled` / `skills.enabled`，重启和升级后继续生效。

页面开关只保存启用状态。通道 host、token、模型 key、数据库连接等敏感配置仍建议放在 `.env` 或后续专门的密钥管理里，不直接写入前端可见配置。

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
curl http://127.0.0.1:8080/api/v1/system/status
```

启用 API token 后：

```powershell
curl -H "Authorization: Bearer 你的token" http://127.0.0.1:8080/api/v1/system/status
```

浏览器访问后端根路径，输入 `XBOT_API_TOKEN`，确认：

- 总览状态正常。
- 通道状态正常。
- 对话页能加载会话。
- WebSocket 活动流能收到 `ui.connected`。
- 页面内 Agent 对话不会默认回发原通道。
