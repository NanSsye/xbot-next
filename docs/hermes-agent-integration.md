# Hermes Agent Integration

更新时间：2026-06-26

`xbot-next` 现在内嵌 Hermes Agent，默认不再使用自研 Agent 工具循环作为生产执行核心。

## 运行方式

如果只使用通道和插件，用户不需要安装内置 Agent/Hermes 额外依赖。需要使用内置 Agent 时，安装可选依赖：

```bash
pip install -e .[agent]
```

Hermes 源码随项目放在 `vendor/hermes/`，不需要单独启动 Hermes。

正常启动 xbot 即可：

```bash
xbot run
```

xbot 仍然负责：

- 微信等通道适配
- 插件和 skill 加载
- 消息队列和消费
- 任务、事件、前端 API
- 数据库和运行状态

Hermes 负责：

- Agent 对话循环
- 长任务持续执行
- 工具调用
- session 记忆、上下文压缩和轨迹

## 上下文和记忆边界

通道消息进入 Agent 时，`agent_chat` 插件只传当前触发消息、发送人/会话标识、附件和引用消息。

xbot 不再把完整聊天历史和会话 summary 拼进 Agent 输入，也不再在 Hermes 默认模式下启动 xbot 自研 memory review/curator。

这意味着：

- 没有 `@` 或没有触发 Agent 的群聊消息不会进入 Agent 长期记忆。
- 长期记忆、短期会话、压缩和任务轨迹由 Hermes session 接管。
- xbot 的 conversation store 仍用于消息框架和前端查询，不作为 Agent 记忆源。

## 源码位置

Hermes 源码放在：

```text
vendor/hermes/
```

后续升级 Hermes 时，替换这个目录即可。替换时需要保留 Hermes 自带的 `LICENSE`。

## 配置边界

主聊天模型仍然复用 xbot 根目录 `.env`：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.minimaxi.com/v1
XBOT_LLM_MODEL=MiniMax-M3
XBOT_LLM_API_KEY=...
```

如果使用 OpenAI-compatible 接口，例如 MiniMax `/v1`：

```env
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.minimaxi.com/v1
```

如果使用 Anthropic Messages 兼容接口，例如 MiniMax Anthropic：

```env
XBOT_LLM_PROVIDER=anthropic
XBOT_LLM_BASE_URL=https://api.minimaxi.com/anthropic
```

`XBOT_LLM_PROVIDER=anthropic` 会让 Hermes 使用 Anthropic Messages 格式；不要把 `/v1` 地址和 Anthropic provider 混用。

Hermes 自己的持久化能力使用 `data/hermes/`：

```text
data/hermes/config.yaml
data/hermes/.env
data/hermes/.env.example
```

首次运行时，xbot 会自动创建 `data/hermes/config.yaml` 和 `data/hermes/.env.example`。默认配置会开启：

- Hermes built-in memory：`MEMORY.md` / `USER.md`
- `skills_list` / `skill_view` / `skill_manage`
- background memory/skill review
- curator skill 生命周期管理
- session DB、轨迹和上下文压缩所需目录

`data/hermes/.env` 只用于 Hermes 专属扩展凭证，例如 OpenRouter、Nous、Anthropic、Gemini、GitHub、搜索服务或外部 memory provider。不要把主聊天模型重复配置到这里，主模型统一由 xbot 根目录 `.env` 注入。

旧版自研 Agent 执行链已经移除，以下配置不再用于 Agent 执行：

```text
XBOT_AGENT_TOOLSETS_*
XBOT_AGENT_CACHE_*
XBOT_AGENT_MEMORY_COMPACTION_*
XBOT_AGENT_WORKSPACE_*
XBOT_AGENT_MCP_ENABLED
XBOT_LLM_MULTIMODAL_*
```

通道、插件、任务记录、事件流、后台任务和定时任务仍由 xbot 框架提供；Agent 推理和工具执行只走 Hermes。

## 869 权限与工具策略

Hermes 仍然负责完整 Agent 循环，但 869 通道会在 xbot wrapper 层给每条触发消息打权限标签：

```text
admin   管理员，完整 Hermes 工具权限
member  普通成员，受限工具权限
guest   访客，只聊天
```

同一个群不会因为权限不同拆成多个 Hermes session。`channel:wechat:wechat869:群ID`、`:member`、`:guest`、旧的 `:restricted` 都会映射回同一个 Hermes session，因此群记忆保持连续。

普通成员不是完全禁用工具，而是通过 xbot 的硬策略限制：

- 文件工具只能访问 `XBOT_AGENT_MEMBER_WORKSPACE_ROOTS` 内的路径。
- 终端工具只能在授权目录内执行，且会拦截网段扫描、内网探测、访问私有 IP 的命令。
- 公网搜索/公开网页读取可以开启；`localhost`、内网 IP、私有网段、`.local` 会被拒绝。
- 高风险工具如 `execute_code`、`delegate_task`、`cronjob`、`process`、主动 `send_message`、浏览器控制默认拒绝。

配置示例：

```env
XBOT_WECHAT869_ADMIN_WXIDS=xianan96928
XBOT_WECHAT869_MEMBER_WXIDS=
XBOT_WECHAT869_DEFAULT_PROFILE=member

XBOT_AGENT_MEMBER_POLICY_ENABLED=true
XBOT_AGENT_MEMBER_WORKSPACE_ROOTS=workspace,.agent-workspace
XBOT_AGENT_MEMBER_ALLOW_TERMINAL=true
XBOT_AGENT_MEMBER_ALLOW_PUBLIC_WEB=true
XBOT_AGENT_MEMBER_BLOCK_PRIVATE_NETWORK=true
```

授权目录可以写相对路径或绝对路径。相对路径按 xbot 启动时的项目根目录解析，例如桌面生产目录 `C:\Users\Administrator\Desktop\xbot-next` 下：

```env
XBOT_AGENT_MEMBER_WORKSPACE_ROOTS=workspace,.agent-workspace
```

等价于授权：

```text
C:\Users\Administrator\Desktop\xbot-next\workspace
C:\Users\Administrator\Desktop\xbot-next\.agent-workspace
```

## 运行数据

Hermes 的运行数据默认写入：

```text
data/hermes/
```

Docker 和本地部署只要持久化项目目录或 `data/`，Hermes session、memory、skills、curator 状态和轨迹就会一起保留。
