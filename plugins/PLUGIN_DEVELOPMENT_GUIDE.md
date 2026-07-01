# xbot-next 插件开发手册

适用目录：`plugins/<PluginName>/`

## 1. 插件最小结构

```text
plugins/MyPlugin/
├─ plugin.toml      # 插件清单，必须
├─ config.toml      # 插件配置，建议
├─ main.py          # 插件入口，必须
└─ data/            # 运行数据，按需创建
```

最小 `plugin.toml`：

```toml
name = "MyPlugin"
version = "1.0.0"
entry = "main:MyPlugin"
author = "xbot"
description = "插件说明"
enabled = true

[routing]
enabled = true
priority = 100
exclusive = false
message_types = ["text"]
platforms = ["wechat"]
adapters = ["wechat869"]
scopes = ["group"]
```

最小 `main.py`：

```python
from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext


class MyPlugin(PluginBase):
    name = "MyPlugin"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        self.ctx = ctx

    async def on_unload(self) -> None:
        return None

    async def on_message(self, message: Message, ctx: PluginContext):
        if message.content == "ping":
            return Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="text",
                content="pong",
            )
        return False
```

## 2. 生命周期

插件继承 `PluginBase`：

```python
async def on_load(self, ctx): ...
async def on_unload(self): ...
async def on_message(self, message, ctx): ...
def agent_tools(self): ...
```

返回值规则：

| 返回值 | 含义 |
|---|---|
| `None` / `False` | 未处理，继续给后续插件 |
| `True` | 已处理，停止后续普通插件 |
| `Reply` | 框架发送回复，并视为已处理 |

## 3. 路由规则

`plugin.toml` 的 `[routing]` 决定插件是否收到消息。

常用字段：

| 字段 | 说明 |
|---|---|
| `priority` | 数字越小越先执行 |
| `exclusive` | 命中后是否独占消息 |
| `fallback` | 作为兜底插件最后执行 |
| `message_types` | `text` / `image` / `file` / `event` |
| `platforms` | 如 `wechat` |
| `adapters` | 如 `wechat869` |
| `scopes` | `group` / `direct` |
| `prefixes` | 内容前缀触发 |
| `keywords` | 包含关键词触发 |
| `exact` | 完全匹配触发 |

注意：

- `priority` 会影响插件抢消息；命令插件应排在通用 AI 插件前面。
- `exclusive = true` 会阻止后续插件处理，慎用。
- 没有 `prefixes/keywords/exact` 时，只要平台、类型、范围匹配就会进入插件。

## 4. Message 字段

```python
message.id              # 消息 ID
message.platform        # wechat
message.adapter         # wechat869
message.type            # text/image/file/event
message.conversation_id # 标准会话 ID
message.sender_id       # 发送人 wxid
message.sender_name     # 昵称
message.content         # 文本内容
message.raw             # 协议原始字段
message.timestamp       # 消息时间
```

微信群会话 ID 通常是：

```text
wechat:wechat869:group:<群号@chatroom>
```

发送到微信协议时通常需要原始群号：

```python
raw_group = message.conversation_id.split(":")[-1]
```

## 5. 发送消息

推荐返回 `Reply`：

```python
return Reply(
    platform="wechat",
    adapter="wechat869",
    conversation_id=message.conversation_id,
    type="text",
    content="回复内容",
)
```

也可用 `ctx.send_reply`：

```python
await ctx.send_reply(Reply(...))
```

发送图片/文件时，确认路径在容器内可读。

## 6. 配置读取

`ctx.config` 是插件配置合并后的 dict。

推荐格式：

```toml
[basic]
enable = true

[MyPlugin]
foo = "bar"
```

读取：

```python
cfg = ctx.config or {}
pcfg = cfg.get("MyPlugin", {})
self.enable = bool(cfg.get("basic", {}).get("enable", pcfg.get("enable", True)))
self.foo = str(pcfg.get("foo", "bar"))
```

不要在代码里写死用户 IP、Key、群号；放 `config.toml` 或根目录 `.env`。

## 7. 访问框架数据库

插件可通过 `ctx.conversations.repository_provider()` 访问框架会话库：

```python
from sqlalchemy import select
from xbot.storage.models import ConversationMessageRecord

async with ctx.conversations.repository_provider() as repo:
    session = repo.session
    rows = (await session.execute(
        select(ConversationMessageRecord)
        .where(ConversationMessageRecord.conversation_id == conversation_id)
        .order_by(ConversationMessageRecord.created_at.desc())
        .limit(50)
    )).scalars().all()
```

注意：

- 容器内数据库地址优先使用 `.env`：`postgres:5432`。
- 宿主机访问映射端口通常是 `8549`。
- 不要给插件单独硬编码 `192.168.x.x`，否则换机器会坏。

## 8. 定时任务

在 `on_load` 创建任务，在 `on_unload` 取消：

```python
self.task = asyncio.create_task(self._loop())

async def on_unload(self):
    if self.task:
        self.task.cancel()
```

注意：

- 循环里必须 `await asyncio.sleep(...)`，不能死循环占满 CPU。
- 定时任务异常要 catch 并记录日志，避免任务静默死亡。
- 群发任务要做防重复。

## 9. 日志规范

使用：

```python
from loguru import logger
logger.info("[MyPlugin] 已加载")
logger.warning("[MyPlugin] 外部服务失败: {}", exc)
logger.exception("[MyPlugin] 未预期异常")
```

建议：

- 正常轮询不要刷屏。
- 调试日志加开关。
- 错误日志保留关键 ID：群号、消息 ID、接口 URL、状态码。

## 10. 商用注意事项

- 不要把真实 API Key 提交到公共仓库。
- 外部 HTTP 调用必须设置 timeout、retry。
- 插件处理消息要快速返回；耗时任务用后台任务或 `asyncio.to_thread`。
- 所有用户输入都当作不可信内容处理。
- HTML 模板渲染用户内容必须 `escape()`。
- 文件路径必须限制在插件目录或工作目录内。
- 图片/文件发送前确认文件存在、大小合理、容器内可读。
- 数据库查询必须分页/limit，禁止无条件全表扫描。
- 插件默认不要 `exclusive = true`，除非确定要截断后续插件。

## 11. 常见问题

### 插件后台不显示

检查：

- `plugins/<PluginName>/plugin.toml` 是否存在。
- `entry = "main:ClassName"` 是否和类名一致。
- `main.py` 是否能被 Python import。
- 容器是否已重启。

### 插件不触发

检查：

- `enabled = true`
- `[routing].enabled = true`
- `platforms/adapters/scopes/message_types` 是否匹配。
- 是否被更高优先级且 `exclusive = true` 的插件抢走。

### 群聊记录查不到

数据库标准会话 ID 通常是：

```text
wechat:wechat869:group:47440917520@chatroom
```

如果拿到的是：

```text
47440917520@chatroom
```

需要先从 `conversations.raw_id` 解析到标准 `id`。

### 修改代码没生效

后端 Python 代码一般需要重启容器：

```bash
docker compose up -d --force-recreate xbot
```

前端页面改动如果是生产构建，需要重新 build。

## 12. 发布前检查清单

- [ ] `python -m py_compile plugins/<PluginName>/main.py`
- [ ] `plugin.toml` 可解析，`entry` 正确。
- [ ] 配置项有默认值。
- [ ] 无硬编码本机 IP、绝对路径、真实密钥。
- [ ] 外部接口有 timeout。
- [ ] 数据库查询有 limit。
- [ ] 容器重启后插件能加载。
- [ ] 群聊/私聊/图片/文本等目标场景实测通过。

