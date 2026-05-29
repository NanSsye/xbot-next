# xbot Next Backend Framework Design

## 1. 目标

`xbot-next` 是一个全新的后端框架，不以当前项目代码为迁移基础，只参考当前项目的能力模型。

第一阶段只建设后端，不建设前端。后端需要先做到可启动、可配置、可接入消息、可加载插件、可通过 API 管理运行状态。前端在后端 API 稳定后再单独搭建。

核心目标：

- 多平台消息机器人框架，而不是单一微信机器人。
- 核心运行时与平台协议解耦。
- 插件系统独立、可发现、可启停、可配置。
- 管理 API 独立，未来前端只消费 API。
- 消息模型统一，插件不直接依赖具体平台协议字段。
- 配置、日志、存储、队列、生命周期全部模块化。

## 2. 非目标

第一版不做这些事情：

- 不复刻旧管理后台页面。
- 不直接迁移旧项目的大型 `admin/server.py`。
- 不兼容所有旧插件。
- 不实现完整插件市场。
- 不实现复杂文件管理、终端代理、联系人同步等高级后台能力。
- 不绑定微信协议作为核心模型。

这些可以作为后续能力逐步加入。

## 3. 技术选型

推荐后端栈：

- Python 3.11+
- FastAPI
- Pydantic v2
- pydantic-settings
- Uvicorn
- SQLAlchemy 2.x
- PostgreSQL 作为默认主存储
- Alembic 作为正式数据库 migration 工具链
- Redis 作为可选消息队列
- APScheduler 作为可选定时任务调度器
- Loguru 或标准 logging 封装
- Typer 作为 CLI
- pytest 作为测试框架
- anyio 作为同步兼容和任务并发辅助

原则：

- 框架代码放在 `src/xbot/`。
- 外部插件默认放在项目根目录 `plugins/`。
- Skill 默认放在项目根目录 `skills/`。
- 配置默认放在 `configs/xbot.toml`。
- 运行数据默认放在 `data/`。
- 运行模型采用 `async-first, sync-compatible`。

## 4. 当前实现进度

更新时间：2026-05-29

已完成：

- [x] 新建独立后端目录 `xbot-next/`。
- [x] 建立 `pyproject.toml`，项目可 editable install。
- [x] 建立 `src/xbot/` 模块化骨架。
- [x] 建立 FastAPI app 工厂和 `/api/v1` router。
- [x] 建立配置加载，默认配置文件为 `configs/xbot.toml`。
- [x] 默认主存储切换为 PostgreSQL，SQLAlchemy URL 使用 `postgresql+asyncpg`。
- [x] 明确工程原则：正式实现优先，内存实现只作为测试/dev fallback。
- [x] 建立 async-first 的 `XBotEngine` 生命周期空实现。
- [x] 建立 WebAdapter 空实现和 adapter registry。
- [x] 建立 PluginBase、PluginManager、plugin manifest/loader。
- [x] 建立 SkillManager、skill manifest/loader。
- [x] 建立 AgentRuntime 空壳、ToolRegistry、ToolExecutor、PolicyEngine、Workspace、MemoryStore。
- [x] 添加 Echo 示例插件。
- [x] 添加 `code_assistant` 示例 skill。
- [x] 补齐 adapters API。
- [x] 补齐 messages simulate/recent API。
- [x] 补齐 agent policy validate API。
- [x] 补齐 agent memory list/create/delete/compact API。
- [x] 添加内存态消息存储，用于第一版消息闭环验证。
- [x] 补齐插件 enable/disable API 和 manager 内存状态管理。
- [x] 补齐 skill enable/disable API 和 manager 内存状态管理。
- [x] 保留 PostgreSQL schema init 测试辅助方法：`Storage.init_schema()`。
- [x] 添加 CLI 数据库初始化命令：`xbot db-init`，内部走 Alembic upgrade。
- [x] 将消息队列和会话系统设计写入文档。
- [x] 实现 MessageEnvelope、DedupeService、MessageConsumer 的内存版基础链路。
- [x] 实现 ConversationManager、SessionStore、ContextWindow 的内存版基础链路。
- [x] messages simulate 已接入 envelope、dedupe、conversation touch 和 plugin dispatch。
- [x] 新增 conversations API 的基础路由。
- [x] PostgreSQL metadata 已补齐 message envelope、dead letter、conversation 相关表。
- [x] Redis Streams 队列实现已落地，使用 consumer group 和 ack。
- [x] MessageConsumer 已接入 Engine 后台生命周期。
- [x] messages simulate 已改为发布到队列，由后台 consumer 消费。
- [x] MessageRepository 和 ConversationRepository 已从空类推进到 PostgreSQL async repository 基础实现。
- [x] Storage 已提供 repository factory。
- [x] ReplyRecord 和 MessageRepository.save_reply 已实现，Engine send_reply 已接入存储和 adapter send。
- [x] ConversationManager 已改为 repository provider 优先，读写都可走 PostgreSQL repository。
- [x] PluginRepository 已实现 PostgreSQL async 基础操作，并接入 PluginManager。
- [x] SkillRepository 已实现 PostgreSQL async 基础操作，并接入 SkillManager。
- [x] AgentRepository 已实现 PostgreSQL async task/event/memory 基础操作，并接入 AgentRuntime。
- [x] 补齐正式 Alembic migration 工具链：`alembic.ini`、`migrations/env.py`、`0001_initial_schema`。
- [x] 添加数据库 migration CLI：`xbot db-upgrade`、`xbot db-current`、`xbot db-downgrade`。
- [x] MessageStore 已改为 PostgreSQL repository 优先，内存 store 仅作为 dev/test fallback。
- [x] messages recent/recent-replies API 已接入 MessageRepository 查询路径。
- [x] conversations list API 已支持 limit，并通过 ConversationRepository 查询路径。
- [x] MessageConsumer 已接入 MessageStore，消费入站 envelope/message 时可落 PostgreSQL。
- [x] 增加 Redis Streams 集成测试环境，使用独立 `xbot:test:*` stream 并在测试后清理。
- [x] Redis Streams 集成测试已验证 publish/consume/ack 和 pending 清理路径。
- [x] PostgreSQL migration 实库验证完成，`xbot` database 已升级到 Alembic revision `0001 (head)`。
- [x] CLI 支持 `python -m xbot.cli.main ...` 直接执行命令。
- [x] 运行时已接入 PostgreSQL 自动 bootstrap：检测、创建 database/role、执行 migration。
- [x] 添加 `xbot db-bootstrap` 命令，用于显式触发同一套自动初始化流程。
- [x] 真实后台启动验证完成：FastAPI 启动、Alembic 启动检查、状态 API、消息 simulate、recent 查询和会话查询均通过。
- [x] Agent 工具正式化第一版完成：文件读、写、列目录、删除、shell 执行工具已注册。
- [x] Agent 工具调用已接入 policy guard 和 `agent_events` 审计事件。
- [x] Agent tools execute API 已落地，并完成真实后台调用验证。
- [x] Agent LLM provider 第一版完成：OpenAI-compatible provider、禁用 fallback、`llm.*` 审计事件。
- [x] Agent LLM 状态 API 已落地，并完成真实后台默认关闭路径验证。
- [x] `.env` 自动加载已接入配置系统，环境变量仍拥有最高优先级，可用 `XBOT_LOAD_DOTENV=false` 关闭。
- [x] Agent 规划和工具自动调用循环第一版完成：LLM JSON 计划、工具执行、结果回填、最终回答。
- [x] Agent 规划循环已用真实 LLM 验证：模型请求 `filesystem.read_file`，Agent 执行工具并返回最终回答。
- [x] Wechat869 真实通道第一版完成：复用已登录 869 服务，不做登录流程，支持私聊文本、群聊文本、群聊 @ 识别和文本回复。
- [x] 插件路由第一版完成：插件可声明触发词、前缀、优先级、fallback 和独占处理。
- [x] Agent 聊天桥接第一版完成：通道消息先走插件，插件未处理时再由 `agent_chat` fallback 插件转入 Agent。
- [x] Agent 会话上下文已带入平台、scope、conversation_id、sender_id、raw metadata、最近消息和时间信息，供模型判断私聊/群聊、发送者和回复目标。
- [x] Agent 工具调用输出已收敛：默认不向用户展示 `tool_calls` 等内部规划 JSON，只展示最终回答。
- [x] Agent 工具自动调用循环已支持多轮工具调用，按任务完成状态继续推进，并写入 `agent_events` 审计。
- [x] Agent 长上下文策略第一版完成：会话历史按 conversation 归档，支持上下文读取和压缩摘要入口。
- [x] Agent 工具结果缓存第一版完成：对可复用的只读工具结果做短 TTL 缓存，降低重复 LLM/tool 循环成本。
- [x] Agent 权限模型已支持 safe/developer/admin 三档，并通过环境变量显式开启高权限模式。
- [x] Agent 当前时间注入已完成，避免模型缺少日期、时区和当前时间上下文。
- [x] Wechat869 Adapter 已接入本项目内部实现：支持 WS 收消息、私聊/群聊识别、@ 识别、文本清洗、队列发布和文本回复。
- [x] Wechat869 媒体发送 Skill 第一版已接入：Agent 可通过 `skill.run` 调用 869 发送文本、图片、视频、语音、音乐、链接和文件。
- [x] MCP 原生支持第一版完成：支持配置 stdio / Streamable HTTP MCP server，启动时发现工具并注册为 `mcp_{server}_{tool}`。
- [x] MCP 配置已接入 `.env` / `configs/xbot.toml`，`mcp` SDK 已提升为主依赖，安装项目时默认具备 MCP client 能力。
- [x] Agent 工具体系规范化第一步完成：内置 `filesystem`、`shell`、`skill` 工具注册已从 `AgentRuntime` 拆到 `xbot.agent.tools.builtin`。
- [x] Tool metadata 第一版完成：`ToolDefinition` 已支持 `toolset`、`source`、`cacheable`、`timeout_seconds`、`invalidates_cache` 和 `metadata`。
- [x] 工具缓存策略已从 `AgentRuntime` 迁出到 `xbot.agent.tools.cache_policy.ToolCachePolicy`，由 tool metadata 决定是否缓存和是否清空缓存。
- [x] `skill.run` 具体执行逻辑已从 `AgentRuntime` 迁出到 `xbot.agent.tools.skill_provider.SkillToolProvider`。
- [x] MCP 增强第一版完成：支持 include/exclude 工具过滤、server status、reload API、按 server source 重新注册工具和更完整错误状态。
- [x] Toolset 可见性第一版完成：Agent prompt 构建时按 API/私聊/群聊选择可见 toolset；admin 模式默认可见所有已注册工具。
- [x] Agent 工具 provider 扩展第一版完成：Plugin 工具 provider、浏览器截图、只读数据库查询、Git/GitHub 只读工具已接入同一套 metadata/toolset/cache/policy 模型。
- [x] Agent 工具 provider 二阶段完成：浏览器交互动作、数据库 schema introspection、GitHub issue/PR 操作和插件工具 manifest 化已接入。
- [x] Agent 工具 provider 三阶段第一版完成：浏览器持久会话工具、SQLAlchemy inspector 跨方言数据库 schema introspection、GitHub GraphQL/Actions 工具、插件工具权限查询 API 已接入同一套 metadata/toolset/cache/policy 模型。
- [x] Agent 工具体验对齐 Codex 第一版完成：EnvironmentProvider、BackgroundTaskManager、ToolFallbackPolicy 已接入，支持环境探测、后台工具任务、结构化错误和 fallback 建议。
- [x] Agent 工具体验对齐 Codex 二阶段第一版完成：后台任务完成后可按通道主动回发，后台任务已接入 PostgreSQL 持久化表，fallback 已支持只读建议工具自动降级执行。
- [x] Agent 工具体验对齐 Codex 三阶段第一版完成：长任务工具已标记 `background_candidate`，后台任务可恢复/安全重放只读任务，timeout fallback 可自动转入后台任务。
- [x] Agent 工具体验对齐 Codex 四阶段第一版完成：后台任务 overview API、失败任务 replay API、通道场景按 provider metadata 自动后台执行策略已落地。
- [x] Agent 工具调用解析增强：支持宽容解析非标准 `{"tool": ...}`、半坏 `tool_calls` JSON，并防止内部工具调用 JSON 外泄到用户回复。
- [x] `filesystem.read_file` 已增加目录路径保护，目录读取会提示改用 `filesystem.list_dir`，避免 Windows 上目录读取显示为权限错误。
- [x] 终端 Agent 对话模式第一阶段完成：新增 `python -m xbot.cli.main chat`，复用同一套 `AgentRuntime`、toolset、后台任务和 slash command。
- [x] 终端 Agent 对话模式五阶段第一版完成：终端会话内保留最近 Agent 事件和后台任务事件，新增 `/events [n]` 与 `/logs [n]` 用于回看工具执行链路和后台任务结果。
- [x] 终端 Agent 对话模式六阶段第一版完成：新增 `chat --tui` Textual 全屏终端 UI，左侧对话、右侧事件、底部输入框，复用现有 slash command、AgentRuntime、工具事件和后台任务事件；考虑 Windows 中文输入法兼容性，`xbot` 无参数默认进入原生输入的普通终端对话模式，`--fancy-input` 才启用 prompt_toolkit 补全/历史。
- [x] 终端 Hermes 对齐三阶段第一版完成：activity 面板、自然语言流式输出、stream chunk 去重、启动模型/工具/插件/skill 概览、工具输入/输出摘要分层和当前任务 `Ctrl+C` 取消已落地。
- [x] 终端 Hermes 对齐四阶段第一版完成：`--fancy-input` 已接入 prompt_toolkit 多行输入、历史/补全、`patch_stdout` 输出保护和底部状态栏；默认仍保留 Windows 中文输入更稳的原生输入。
- [x] 终端 Hermes 对齐五阶段第一版完成：新增 `xbot chat-bridge` JSONL stdin/stdout 协议入口，外部 TUI/Web/PTY 前端可作为独立进程接入同一套 AgentRuntime 事件和 final 输出。
- [x] 终端首页视觉增强第二版完成：普通 `xbot` 启动页改为接近 Hermes CLI 的双栏 banner，左侧品牌 ASCII、ready 状态、模型/会话信息，右侧按 toolset/skill 展示可用能力，并保留 Windows 编码安全 fallback。
- [x] 终端对话视觉增强第二版完成：参考 Hermes classic CLI，把用户输入改为 prompt 行，assistant 改为轻量 `xbot` 标题块流式输出，短系统提示保留一行状态，避免对话区堆叠大面板。
- [x] 终端交互修复：取消用户输入二次显示，补充 stream restart/suffix 去重，避免 OpenAI-compatible 流式接口重复输出回答后半段。
- [x] 终端 Hermes 状态栏增强：每轮回复后显示模型名、上下文占用、百分比进度条、本轮耗时和 LLM 耗时；上下文已用量优先读取接口 usage，窗口总量支持 `agent.llm.context_window_tokens` / `XBOT_LLM_CONTEXT_WINDOW_TOKENS`，未配置时按模型名兜底。
- [x] 添加基础测试，当前 `python -m pytest -q` 通过，结果为 `122 passed`。

进行中：

- [ ] Toolset 二阶段：当前已按 API/私聊/群聊控制可见范围，admin 默认全部可见；下一步细化到具体 adapter、用户身份、群管理员和会话状态。
- [ ] MCP 二阶段：当前已有 include/exclude、status、reload 和失败状态记录；下一步补自动重连退避、周期健康检查、失败工具降级和连接池隔离。
- [ ] Wechat869 生产稳定性验证：当前已完成 WS 收消息和回复链路；下一步验证长连接重连、群聊高频消息、异常消息格式和生产日志可观测性。
- [ ] Agent 工具 provider 四阶段：浏览器会话生命周期接入 runtime stop、数据库更多方言边界验证、GitHub 写操作审批细化、插件工具权限持久化开关和前端 UI。
- [ ] Agent 工具体验对齐 Codex 五阶段：真正前端后台任务页面、后台任务失败原因聚合、按工具/平台配置自动后台策略。
- [ ] 终端 Hermes 对齐六阶段：基于 `chat-bridge` 实现真正独立 UI 进程的 TUI/Web/PTY 前端，并继续规避 Windows 中文 IME 兼容问题。

尚未开始：

- [ ] 前端管理界面。
- [ ] 旧插件兼容层。

## 5. 总体架构

```text
client/platform
  -> adapter
  -> message normalizer
  -> message pipeline
  -> plugin dispatcher
  -> reply router
  -> adapter sender

admin client
  -> FastAPI API
  -> services
  -> runtime engine / storage / plugin manager
```

核心分层：

- `api`: HTTP API 层，只做请求校验和响应转换。
- `services`: 业务服务层，承接 API 与核心运行时。
- `runtime`: 框架生命周期、运行状态、引擎调度。
- `messaging`: 标准消息模型、队列、回复路由、消息流水线。
- `adapters`: 平台适配器。
- `plugins`: 插件协议、插件加载、插件调度。
- `skills`: 面向智能体的能力说明、工作流和工具编排单元。
- `agent`: 内置智能体运行时，负责规划、调用工具、读写代码和执行任务。
- `storage`: 数据库和仓储。
- `core`: 配置、日志、安全、异常、事件等基础设施。

## 6. 模块化原则

新框架必须做到“能力模块化”，不是只按目录拆文件。

模块化目标：

- 每个模块有清晰职责。
- 每个模块有明确公开接口。
- 模块之间通过 service、protocol、context 或 registry 交互。
- 禁止跨层直接访问内部实现。
- 第一版可以保留测试用内存适配器，但正式能力必须按生产路径实现。
- 禁止把“简易版”作为阶段目标；内存实现只允许作为测试/dev fallback。
- 禁止为了快速跑通而绕过 repository、queue、policy、consumer 等正式边界。
- 允许第一版有接口占位，但不能用占位逻辑替代已确定的正式架构路径。

### 6.1 模块职责

```text
api
  -> HTTP 输入输出、请求校验、响应转换

services
  -> 业务用例编排，连接 API、runtime、storage、manager

runtime
  -> 框架生命周期、主引擎、运行状态

messaging
  -> 标准消息模型、消息队列、pipeline、reply router

adapters
  -> 平台接入、平台消息标准化、平台发送

plugins
  -> 插件协议、插件加载、插件启停、插件事件分发

skills
  -> skill manifest、SKILL.md 加载、skill 检索和启停

agent
  -> AgentRuntime、工具调用、权限、工作区、记忆、压缩

storage
  -> PostgreSQL session、ORM model、repository、事务边界

core
  -> 配置、日志、异常、事件、安全、通用基础设施

schemas
  -> API DTO 和跨边界数据结构

cli
  -> 命令行入口，调用 service，不写业务逻辑
```

### 6.2 依赖方向

推荐依赖方向：

```text
api
  -> services

cli
  -> services

services
  -> runtime
  -> storage repositories
  -> plugin manager
  -> skill manager
  -> agent runtime

runtime
  -> messaging
  -> adapters registry
  -> plugin manager
  -> skill manager
  -> agent runtime

agent
  -> tool registry
  -> policy engine
  -> workspace guard
  -> memory store
  -> plugin tools
  -> skill manager

adapters
  -> messaging models

plugins
  -> plugin context
  -> messaging models

skills
  -> skill manifest
  -> skill content

storage
  -> core config
```

禁止依赖方向：

```text
storage -> api
storage -> FastAPI Request
plugins -> FastAPI app
adapters -> concrete plugins
api -> ORM model
api -> direct database session
agent -> raw filesystem without WorkspaceGuard
agent -> raw shell without ToolExecutor
tools -> bypass PolicyEngine
skills -> execute code directly
```

### 6.3 模块公开接口

每个模块只暴露少量稳定接口。

示例：

```text
runtime
  -> XBotEngine
  -> RuntimeStatus

plugins
  -> PluginBase
  -> PluginManager
  -> PluginContext

skills
  -> SkillManager
  -> SkillManifest

agent
  -> AgentRuntime
  -> ToolRegistry
  -> ToolExecutor
  -> PolicyEngine
  -> MemoryStore

messaging
  -> Message
  -> Reply
  -> MessagePipeline

storage
  -> create_session
  -> repositories
```

模块内部文件可以变化，但公开接口要保持稳定。

### 6.4 模块启动顺序

框架启动顺序：

```text
load config
  -> init logging
  -> init storage
  -> run migrations
  -> init repositories
  -> init event bus
  -> init messaging queue
  -> init plugin manager
  -> init skill manager
  -> init tool registry
  -> init agent runtime
  -> init adapter registry
  -> init XBotEngine
  -> start adapters
  -> start background tasks
  -> expose API ready
```

框架停止顺序：

```text
stop accepting new tasks
  -> cancel or drain agent tasks
  -> stop adapters
  -> unload plugins
  -> flush memories and audit events
  -> close queues
  -> close database sessions
  -> shutdown logging
```

### 6.5 第一版骨架要求

第一版即使功能未完成，也必须先建立模块骨架：

- `api/v1/router.py` 统一注册 API。
- 每类 API 一个独立 router 文件。
- 每个 service 一个独立 service 文件。
- 每个 manager 独立模块。
- 每个 repository 独立模块。
- Agent 的 tool、policy、memory、workspace 不混写。
- Plugin 和 Skill 完全分离。
- 配置模型按模块拆分。
- 测试按模块放置。
- 正式实现优先落到 PostgreSQL repository、Redis Streams、后台 consumer、policy guard 等目标架构。
- 内存队列、内存会话、内存记忆只能作为测试替身或开发 fallback，不能作为生产路径。

禁止第一版出现新的“大一统 server.py”。

### 6.6 模块测试策略

测试目录建议：

```text
tests/
  unit/
    core/
    messaging/
    plugins/
    skills/
    agent/
    storage/
  integration/
    api/
    runtime/
    postgres/
```

第一版重点测试：

- 配置加载。
- FastAPI app 创建。
- PostgreSQL session 创建。
- Runtime start/stop。
- PluginManager 空加载。
- SkillManager 空加载。
- ToolRegistry 注册。
- PolicyEngine 路径拦截。
- MemoryCompressor 基础压缩。

## 7. 目录结构

```text
xbot-next/
  README.md
  pyproject.toml
  .env.example

  configs/
    xbot.toml

  data/
    .gitkeep

  docs/
    backend-framework-design.md

  plugins/
    echo/
      plugin.toml
      main.py

  skills/
    code_assistant/
      skill.toml
      SKILL.md

  src/
    xbot/
      __init__.py

      app/
        __init__.py
        main.py
        lifespan.py
        deps.py

      api/
        __init__.py
        v1/
          __init__.py
          router.py
          auth.py
          bot.py
          system.py
          plugins.py
          adapters.py
          messages.py
          config.py

      core/
        __init__.py
        config.py
        logging.py
        exceptions.py
        events.py
        security.py

      runtime/
        __init__.py
        engine.py
        context.py
        status.py
        lifecycle.py
        scheduler.py

      agent/
        __init__.py
        runtime.py
        planner.py
        tool_registry.py
        tool_executor.py
        workspace.py
        memory.py
        compression.py
        policy.py

      messaging/
        __init__.py
        models.py
        pipeline.py
        consumer.py
        dedupe.py
        queue.py
        memory_queue.py
        redis_queue.py
        reply_router.py
        message_store.py

      conversations/
        __init__.py
        models.py
        manager.py
        session_store.py
        context_window.py

      adapters/
        __init__.py
        base.py
        registry.py
        web/
          __init__.py
          adapter.py

      plugins/
        __init__.py
        base.py
        context.py
        manifest.py
        loader.py
        manager.py
        registry.py
        permissions.py

      skills/
        __init__.py
        manifest.py
        loader.py
        manager.py
        registry.py

      services/
        __init__.py
        bot_service.py
        plugin_service.py
        adapter_service.py
        message_service.py
        conversation_service.py
        agent_service.py
        skill_service.py
        system_service.py
        config_service.py

      storage/
        __init__.py
        session.py
        models.py
        repositories/
          __init__.py
          plugin_repo.py
          message_repo.py
          conversation_repo.py
          config_repo.py
          agent_repo.py
          skill_repo.py

      schemas/
        __init__.py
        common.py
        bot.py
        plugin.py
        adapter.py
        message.py
        conversation.py
        system.py

      cli/
        __init__.py
        main.py
```

## 8. 核心运行时

`XBotEngine` 是新框架的核心对象。

职责：

- 加载配置。
- 初始化日志。
- 初始化存储。
- 初始化队列。
- 注册适配器。
- 加载插件。
- 启动和停止运行时。
- 接收标准消息。
- 调用消息流水线。
- 分发消息给插件。
- 处理插件回复。
- 维护运行状态。

建议接口：

```python
class XBotEngine:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def restart(self) -> None: ...
    async def dispatch_message(self, message: Message) -> None: ...
    async def send_reply(self, reply: Reply) -> None: ...
    def status(self) -> RuntimeStatus: ...
```

## 9. 异步运行模型

框架采用：

```text
async-first, sync-compatible
```

也就是核心运行时和所有 I/O 边界默认异步，但允许插件和部分工具用同步方式实现。同步代码必须由框架包装到线程池或 worker 中执行，不能阻塞主事件循环。

### 9.1 必须异步的模块

这些模块必须以 async API 为主：

- FastAPI API handler。
- `XBotEngine.start/stop/restart/dispatch_message/send_reply`。
- Adapter 启停、收消息、发消息。
- 消息 pipeline。
- Plugin dispatch 调度器。
- Agent Runtime。
- ToolExecutor。
- PostgreSQL 访问。
- Redis 队列。
- HTTP client。
- WebSocket。
- 后台任务入口。

推荐依赖：

```text
SQLAlchemy AsyncEngine
postgresql+asyncpg
redis.asyncio
httpx.AsyncClient
anyio
```

### 9.2 同步兼容

这些可以允许同步实现：

- 简单插件。
- 旧插件兼容层。
- 简单本地工具。
- CPU 轻量计算。
- 只有同步 SDK 的第三方集成。

框架需要统一检测函数类型：

```python
if inspect.iscoroutinefunction(handler):
    await handler(...)
else:
    await anyio.to_thread.run_sync(handler, ...)
```

同步插件和同步工具不能直接运行在事件循环线程里。

### 9.3 插件接口

插件推荐 async：

```python
class PluginBase:
    async def on_load(self, ctx: PluginContext) -> None: ...
    async def on_unload(self) -> None: ...
    async def on_message(self, message: Message, ctx: PluginContext) -> None: ...
```

但框架允许：

```python
class SimplePlugin:
    def on_message(self, message, ctx):
        ...
```

同步插件由 `PluginManager` 包装执行。

### 9.4 Tool 接口

Tool 推荐 async：

```python
class Tool:
    async def run(self, input, ctx): ...
```

也允许同步：

```python
class SyncTool:
    def run(self, input, ctx): ...
```

`ToolExecutor` 负责判断并隔离执行。

### 9.5 并发控制

必须避免无限并发。

建议配置：

```toml
[runtime.concurrency]
max_message_tasks = 100
max_plugin_tasks = 50
max_agent_tasks = 5
max_tool_tasks = 20
sync_worker_threads = 8
```

规则：

- 每条消息有独立 task，但受总并发限制。
- 每个插件可设置并发上限。
- Agent task 默认低并发，避免多个 Agent 同时改同一批文件。
- 文件写入工具需要 workspace-level lock。
- 同一 task 内的工具调用默认串行，除非 planner 明确声明可并行。

### 9.6 取消和超时

所有长任务必须支持取消和超时：

- message dispatch timeout
- plugin timeout
- tool timeout
- agent task timeout
- HTTP request timeout
- database query timeout

示例配置：

```toml
[runtime.timeout]
message_seconds = 60
plugin_seconds = 30
tool_seconds = 120
agent_task_seconds = 1800
http_seconds = 30
```

取消任务时要尽量写入审计事件，说明任务被取消的位置和原因。

## 10. 标准消息模型

所有平台进入框架前必须转换成统一消息模型。

```python
class Message:
    id: str
    platform: str
    adapter: str
    type: str
    conversation_id: str
    sender_id: str
    sender_name: str | None
    content: str | None
    raw: dict
    timestamp: datetime
```

回复模型：

```python
class Reply:
    platform: str
    adapter: str
    conversation_id: str
    type: str
    content: str
    quote_message_id: str | None = None
```

消息类型第一版只要求：

- `text`
- `image`
- `file`
- `event`

第一版插件可以只处理 `text`。

## 11. 消息队列设计

消息队列是框架核心模块，负责削峰、解耦 adapter、支撑重试和跨进程扩展。

### 11.1 队列分层

队列分两层：

```text
in-process queue
  -> anyio / asyncio memory queue，用于单进程、本地测试、开发环境

distributed queue
  -> Redis Streams，用于生产环境、多进程和多实例部署
```

PostgreSQL 负责持久化、审计和查询，不作为第一版高频消息队列。后续如需要纯 PostgreSQL 部署，可以补 `postgres_queue`，但默认不选它承载高吞吐消息流。

### 11.2 队列主题

建议队列命名：

```text
xbot:messages      # 标准入站消息
xbot:replies       # 标准出站回复
xbot:events        # 系统事件
xbot:agent_tasks   # agent 异步任务
xbot:dead_letters  # 死信队列
```

每类队列由 `MessageQueue` 抽象承接，具体实现：

- `MemoryMessageQueue`
- `RedisStreamQueue`
- `NullQueue`，用于测试或禁用某些后台消费

### 11.3 消息流

标准消息处理链路：

```text
Adapter.receive
  -> Adapter.normalize
  -> MessageQueue.publish
  -> MessageConsumer.consume
  -> DedupeService.check
  -> MessagePipeline.process
  -> ConversationManager.touch
  -> PluginManager.dispatch
  -> AgentRuntime.run_task, when needed
  -> ReplyRouter.route
  -> ReplyQueue.publish
  -> AdapterRegistry.send
```

第一版可以在 API simulate 中短路部分流程，但模块边界必须按这个链路保留。

### 11.4 消息信封

队列中不直接丢裸 `Message`，而是使用 envelope。

```python
class MessageEnvelope:
    id: str
    trace_id: str
    dedupe_key: str
    message: Message
    delivery_attempts: int
    created_at: datetime
    available_at: datetime | None
    headers: dict[str, str]
```

字段说明：

- `id`: 队列消息 ID。
- `trace_id`: 贯穿 adapter、pipeline、plugin、agent、reply 的追踪 ID。
- `dedupe_key`: 幂等键，避免重复处理。
- `delivery_attempts`: 投递次数。
- `available_at`: 延迟重试时间。
- `headers`: 扩展元数据。

### 11.5 重试与死信

消费失败时：

```text
attempts < max_attempts
  -> 延迟重试

attempts >= max_attempts
  -> 写入 xbot:dead_letters
  -> 写入审计事件
```

配置示例：

```toml
[queue.retry]
max_attempts = 3
initial_delay_seconds = 2
max_delay_seconds = 60
backoff = "exponential"
```

### 11.6 幂等与顺序

幂等由 `DedupeService` 负责。

建议 `dedupe_key`：

```text
{platform}:{adapter}:{raw_message_id}
```

如果平台没有 raw message id，则使用：

```text
{platform}:{adapter}:{conversation_id}:{sender_id}:{timestamp}:{content_hash}
```

顺序策略：

- 同一 `conversation_id` 内默认按消息时间顺序处理。
- 不同 conversation 可以并发处理。
- Agent 修改文件类任务默认串行。

### 11.7 配置

```toml
[queue]
type = "memory" # memory | redis
redis_url = "redis://192.168.6.41:6379/15"
main_queue = "xbot:messages"
reply_queue = "xbot:replies"
event_queue = "xbot:events"
agent_task_queue = "xbot:agent_tasks"
dead_letter_queue = "xbot:dead_letters"

[queue.retry]
max_attempts = 3
initial_delay_seconds = 2
max_delay_seconds = 60
backoff = "exponential"
```

如果 Redis 与其他项目共用，不要使用 `/0`。删除 URL 末尾的数据库编号通常仍会回落到 DB 0，因此应显式配置独立 DB，例如 `/15`，并继续使用 `xbot:*` 前缀隔离 key。

## 12. 会话系统设计

会话系统负责当前聊天上下文、参与者、会话状态和插件/Agent 的会话级状态。它和 Agent 记忆系统不是同一个东西。

```text
Conversation Session = 当前对话状态
Agent Memory = 跨任务长期记忆
Message Store = 原始消息记录
```

### 12.1 会话类型

会话类型：

```text
private
group
channel
agent_task
system
```

会话 ID 规范：

```text
{platform}:{adapter}:{scope}:{raw_id}
```

示例：

```text
wechat:web:private:wxid_xxx
wechat:web:group:123@chatroom
telegram:bot:private:123456
web:web:private:user_1
system:xbot:agent_task:task_id
```

### 12.2 ConversationManager 职责

`ConversationManager` 负责：

- 创建或更新会话。
- 维护会话成员。
- 保存最近消息引用。
- 维护会话状态。
- 提供上下文窗口。
- 绑定插件会话状态。
- 绑定 Agent task。
- 控制每个会话的并发处理。

建议接口：

```python
class ConversationManager:
    async def touch(self, message: Message) -> Conversation: ...
    async def append_message(self, conversation_id: str, message: Message) -> None: ...
    async def get_context(self, conversation_id: str, limit: int) -> ConversationContext: ...
    async def get_state(self, conversation_id: str, namespace: str) -> dict: ...
    async def set_state(self, conversation_id: str, namespace: str, value: dict) -> None: ...
```

### 12.3 会话上下文窗口

上下文窗口由 `ContextWindow` 控制。

规则：

- 默认取最近 N 条消息。
- 超过 token 或字符阈值时压缩。
- 插件可以请求自己的 namespace 状态。
- Agent 可以读取会话上下文，但长期记忆仍走 `MemoryStore`。

配置：

```toml
[conversation.context]
recent_messages = 20
max_chars = 16000
auto_summarize = true
summary_every_messages = 50
```

### 12.4 会话状态

会话状态需要 namespace 隔离。

示例：

```text
conversation_id = "web:web:private:user_1"
namespace = "plugin.echo"
state = {"last_command": "/echo hello"}

namespace = "agent"
state = {"active_task_id": "..."}
```

这样插件之间不会互相污染状态。

### 12.5 数据表

建议表：

- `conversations`
  - id
  - platform
  - adapter
  - scope
  - raw_id
  - title
  - created_at
  - updated_at
- `conversation_members`
  - id
  - conversation_id
  - user_id
  - display_name
  - role
  - joined_at
- `conversation_messages`
  - id
  - conversation_id
  - message_id
  - sender_id
  - type
  - content
  - created_at
- `conversation_states`
  - id
  - conversation_id
  - namespace
  - value_json
  - updated_at
- `conversation_summaries`
  - id
  - conversation_id
  - summary
  - from_message_id
  - to_message_id
  - created_at

### 12.6 配置

```toml
[conversation]
enabled = true
store = "postgresql"
default_scope = "private"

[conversation.context]
recent_messages = 20
max_chars = 16000
auto_summarize = true
summary_every_messages = 50

[conversation.concurrency]
per_conversation_serial = true
max_active_conversations = 1000
```

## 13. Adapter 设计

Adapter 只负责平台接入和发送，不负责业务逻辑。

```python
class BaseAdapter:
    name: str
    platform: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, reply: Reply) -> None: ...
    async def normalize(self, raw: dict) -> Message: ...
```

第一版已实现：

- `WebAdapter`：用于本地 API 模拟消息输入，确保核心框架可以独立跑通。
- `Wechat869Adapter`：复用已登录 869 协议服务，不实现登录流程，只负责文本收发通道。

`Wechat869Adapter` 第一阶段能力：

- 通过 WebSocket 接收 869 消息。
- 标准化私聊文本消息。
- 标准化群聊文本消息。
- 识别群聊消息是否 @ 当前 bot。
- 通过 869 `send_text_message` 发送文本回复。
- 图片、文件、语音等富媒体不直接内置在 adapter，后续作为 skill/tool 交给 Agent 按需调用。

后续再实现：

- QQ adapter
- Telegram adapter
- Webhook adapter

## 14. 插件系统

插件是框架的主要扩展点。

插件目录示例：

```text
plugins/echo/
  plugin.toml
  main.py
```

`plugin.toml`：

```toml
name = "echo"
version = "0.1.0"
entry = "main:EchoPlugin"
author = "xbot"
description = "Echo test plugin"

[permissions]
network = false
filesystem = false
admin = false
```

插件可以声明消息路由：

```toml
[routing]
enabled = true
priority = 100
fallback = false
exclusive = true
message_types = ["text"]
platforms = ["wechat"]
adapters = ["wechat869"]
scopes = ["private", "group"]
prefixes = ["/help"]
keywords = ["帮助"]
exact = ["菜单"]
```

路由规则：

- 普通插件先于 Agent 运行。
- `priority` 越小越先匹配。
- `prefixes`、`keywords`、`exact` 用于判断是否命中插件提示词。
- 插件返回 `True`、`Reply`、`{"handled": true}` 或发送了回复，即视为已处理。
- `exclusive = true` 且触发词命中时，即使插件没有回复，也会截断后续 Agent fallback。
- `fallback = true` 的插件最后运行，用于兜底能力，例如 `agent_chat`。
- 因此消息链路是：通道消息 -> 普通插件匹配 -> 插件命中则优先处理 -> 未处理再进入 Agent。

插件基类：

```python
class PluginBase:
    name: str
    version: str

    async def on_load(self, ctx: PluginContext) -> None: ...
    async def on_unload(self) -> None: ...
    async def on_message(self, message: Message, ctx: PluginContext) -> None: ...
```

`PluginContext` 提供：

- 发送回复。
- 调用 Agent Runtime。
- 读取插件配置。
- 访问插件私有数据目录。
- 写日志。
- 读取框架配置的安全子集。

第一版插件管理需要支持：

- 扫描插件目录。
- 读取 manifest。
- 动态加载插件入口。
- 启用插件。
- 禁用插件。
- 卸载插件。
- 按 routing 分发消息到启用插件。
- 支持插件处理截断和 Agent fallback。

内置 `agent_chat` 插件：

- 作为 fallback 插件，不抢普通插件优先级。
- 私聊文本默认进入 Agent。
- 群聊文本只有 @ 当前 bot 时进入 Agent。
- Agent 结果通过统一 `Reply` 路由发回原通道。
- Agent 工具调用仍然走 `PolicyEngine`、`ToolExecutor` 和 `agent_events` 审计。

## 15. 消息流水线

消息进入插件前走 pipeline。

第一版 pipeline：

```text
validate
  -> deduplicate
  -> normalize context
  -> plugin dispatch
  -> reply routing
```

后续 pipeline：

```text
validate
  -> audit log
  -> deduplicate
  -> blacklist / whitelist
  -> permission check
  -> wakeup check
  -> rate limit
  -> plugin dispatch
  -> reply routing
```

pipeline 要设计成可插拔 middleware。

## 16. Agent Runtime

新框架需要内置智能体能力。这个智能体不是普通聊天插件，而是框架级运行时能力，类似一个可以被消息、API、定时任务或插件调用的执行代理。

目标能力：

- 理解用户任务。
- 制定执行计划。
- 调用框架注册的工具。
- 读取项目文件。
- 修改项目文件。
- 执行安全范围内的命令。
- 调用插件能力。
- 调用 skill 工作流。
- 记录任务过程和结果。

核心原则：

- Agent Runtime 属于框架核心能力，不写在普通插件里。
- 工具调用必须经过 `ToolRegistry` 和 `ToolExecutor`。
- 文件读写必须经过 `Workspace` 抽象，不能在 agent 内部任意拼 shell。
- 命令执行必须经过策略检查。
- 高风险工具需要权限策略。
- Agent 可以调用插件和 skill，但插件和 skill 不应该直接控制 agent 内核。

建议接口：

```python
class AgentRuntime:
    async def run_task(self, task: AgentTask) -> AgentResult: ...
    async def continue_task(self, task_id: str, user_input: str) -> AgentResult: ...
    async def cancel_task(self, task_id: str) -> None: ...
```

`AgentTask` 来源：

- 管理 API。
- 聊天消息。
- 插件调用。
- 定时任务。
- 系统事件。

## 17. Tool 体系

工具是智能体可调用的原子能力。

第一版内置工具：

- `filesystem.read_file`
- `filesystem.write_file`
- `filesystem.list_files`
- `shell.exec`
- `plugin.call`
- `skill.run`
- `http.request`

后续工具：

- `git.status`
- `git.diff`
- `git.commit`
- `database.query`
- `browser.search`
- `image.generate`

工具注册示例：

```python
class Tool:
    name: str
    description: str
    input_schema: type
    risk_level: str

    async def run(self, input: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

工具风险级别：

- `read`: 只读。
- `write`: 会写入文件或数据库。
- `execute`: 会执行命令。
- `network`: 会访问外部网络。
- `dangerous`: 需要显式授权或管理员策略。

### 17.1 Tool 体系规范化目标

随着内置工具、Skill 工具、MCP 工具和后续浏览器/数据库/Git 工具增加，Tool 体系必须保持单一模型，不能继续把工具定义散落在 `AgentRuntime` 中。

目标分层：

```text
xbot.agent.runtime
  -> 只负责 Agent task、LLM loop、工具执行编排、审计事件

xbot.agent.tool_registry
  -> 统一工具注册中心，保存 ToolDefinition、schema、risk、metadata

xbot.agent.tool_executor
  -> 统一执行入口，处理 sync/async 隔离、timeout、policy、审计前后钩子

xbot.agent.tools.builtin
  -> 内置 filesystem、shell、skill 工具注册

xbot.agent.mcp
  -> MCP server 连接、工具发现、MCP 工具注册

xbot.agent.tools.toolsets
  -> 工具集、平台可见性、include/exclude、默认启用策略
```

所有工具必须满足：

- 有唯一稳定名称。
- 有 JSON schema。
- 有风险等级。
- 有明确 handler。
- 通过 `ToolExecutor` 执行。
- 不允许绕过 `PolicyEngine` 访问文件、shell、数据库或网络。
- 不允许在 `AgentRuntime` 中直接堆业务工具实现。

### 17.2 Tool 来源

工具来源分为四类：

1. 内置工具：框架自带，例如 filesystem、shell、skill。
2. Plugin 工具：插件对外暴露的可复用能力。
3. Skill 工具：Skill 入口或 Skill action，例如 `skill.run`。
4. MCP 工具：从外部 MCP server 自动发现并注册。

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

### 17.3 Toolset 计划

后续需要加入 Toolset 层，避免所有通道默认看到所有工具。

建议内置 toolset：

```text
core                  -> skill.list, skill.describe
filesystem            -> filesystem.read_file, filesystem.list_dir
filesystem_write      -> filesystem.write_file
filesystem_dangerous  -> filesystem.delete_path
shell                 -> shell.exec
skill                 -> skill.run
mcp                   -> 所有 mcp_* 工具
browser               -> 后续浏览器工具
wechat                -> 微信发送/媒体工具
```

平台默认策略：

- API 调用：按任务配置或管理员配置决定。
- 私聊 Agent：默认 `core + filesystem(read) + skill`，shell 需要显式允许。
- 群聊 Agent：默认更保守，shell/write/delete 需要显式允许。
- 定时任务：按任务 manifest 固定 toolset。

### 17.4 规范化迁移步骤

按低风险顺序推进：

1. [x] 把内置工具注册从 `AgentRuntime` 拆到 `xbot.agent.tools.builtin`。
2. [x] 保持 `ToolRegistry` 和 `ToolExecutor` 接口稳定，先不改变外部 API。
3. [x] 给 `ToolDefinition` 增加 `toolset`、`source`、`cacheable`、`timeout_seconds` 等 metadata。
4. [x] 把缓存策略从 `AgentRuntime._tool_cache_key` 下沉到工具 metadata 或专门的 cache policy。
5. [x] 把 `skill.run` 的具体 skill action 从 `AgentRuntime` 迁出到 skill tool provider。
6. [x] 给 MCP 工具增加 include/exclude、server status API、reload 和错误状态记录。
7. [x] 引入 toolset 解析，按平台和会话 scope 控制可见工具。
8. [x] 收敛 Agent prompt 构建，只从规范化 tool registry 读取可见工具定义。

剩余增强：

- [ ] MCP 自动重连退避和健康检查。
- [ ] Toolset 按具体用户、群管理员和 adapter 配置继续细化。
- [x] Plugin 工具 provider 和浏览器/数据库/Git 工具集接入同一套 metadata。
- [x] 浏览器交互动作、数据库 schema introspection、GitHub issue/PR 操作和插件工具 manifest 化。
- [x] 浏览器持久会话、数据库跨方言 introspection、GitHub GraphQL/Actions 能力和插件工具权限查询 API。

### 17.5 对齐 Codex 式工具体验

当前框架已经建立了 `tool_registry -> tool_executor -> provider handler` 的治理链路。这个链路不能移除，因为权限、审计、缓存、toolset 可见性、插件扩展和 MCP 工具统一注册都依赖它。真正需要优化的不是“少一层”，而是让这层更薄、更快、更可观测，并把长任务和错误恢复交给专门模块处理。

#### 17.5.1 工具链路优化原则

保留统一链路：

```text
LLM plan
  -> ToolRegistry
  -> ToolExecutor
  -> Provider handler
  -> ToolResult
  -> LLM continue/final
```

优化方向：

- `ToolRegistry` 只负责定义、metadata、可见性和查找。
- `ToolExecutor` 只负责执行调度、timeout、sync/async 隔离、审计和统一错误包装。
- 具体能力全部放到 provider，不允许继续塞进 `AgentRuntime`。
- 对高频只读工具使用 metadata 驱动缓存，避免 LLM 循环里重复读取相同状态。
- 对长耗时工具支持后台任务，不阻塞微信/HTTP 请求等待完整结果。

#### 17.5.2 EnvironmentProvider

目标：让 Agent 主动知道当前运行环境，而不是每次靠模型猜或盲目调用 shell。

新增 toolset：

```text
environment
```

建议工具：

```text
environment.snapshot
environment.which
environment.network
environment.ports
environment.runtime
```

返回信息包括：

- 操作系统、架构、当前用户、工作目录。
- Python 版本、虚拟环境路径、pip 可用性。
- Git、GitHub CLI、Node、npm、Playwright、浏览器安装状态。
- 代理环境变量和常用网络连通性。
- 常用端口占用，例如 8080、5432、5433、6379。
- 磁盘剩余空间和 workspace 访问状态。

设计要求：

- `environment.snapshot` 默认只读、可缓存，缓存时间短，例如 30 秒。
- 不暴露敏感环境变量原值，只返回是否存在和脱敏预览。
- 优先使用 Python 标准库和安全命令探测，不让模型自己拼复杂 shell。
- Agent prompt 中应明确：遇到“能不能打开浏览器”“为什么工具不可用”“端口是否占用”等问题，优先调用 environment 工具。

#### 17.5.3 BackgroundTaskManager

目标：解决截图、下载、浏览器操作、GitHub Actions 日志读取、长时间 skill 执行这类任务阻塞聊天通道的问题。

核心模型：

```text
Agent request
  -> start background task
  -> immediate ack reply
  -> task events/progress
  -> final result pushed to conversation
```

建议 API：

```text
POST   /api/v1/agent/background-tasks
GET    /api/v1/agent/background-tasks/overview
GET    /api/v1/agent/background-tasks
GET    /api/v1/agent/background-tasks/{task_id}
POST   /api/v1/agent/background-tasks/{task_id}/replay
POST   /api/v1/agent/background-tasks/{task_id}/cancel
```

建议工具：

```text
task.start
task.status
task.cancel
task.list
```

执行规则：

- 长任务不直接占用 `agent_chat` 的消息处理超时时间。
- 微信场景中，任务开始后先回复“任务已开始”，完成后通过 reply router 主动发送结果。
- 每个后台任务记录 `status`、`progress`、`started_at`、`finished_at`、`source`、`conversation_id`、`sender_id`、`tool_calls`。
- 支持取消、超时、失败重试和最终结果持久化。
- 大文件、截图、日志结果只在消息里发摘要，完整内容保存为 workspace 文件或附件。

当前实现状态：

- [x] `BackgroundTaskManager` 已支持本进程后台工具任务、取消、查询和列表。
- [x] `agent_background_tasks` 表和 Alembic `0003` migration 已加入。
- [x] 后台任务状态变更会写入 Agent repository。
- [x] `task.start` 支持 `notify` 元数据；通道 Agent 场景会自动从 `source` 和 `message_id` 注入回发目标。
- [x] 任务完成、失败或取消后可通过 `engine.send_reply` 主动回发原会话。
- [x] 服务启动时会恢复后台任务记录；已完成/已取消任务进入内存索引，未完成且 `replayable=true` 的只读工具任务会安全重放一次。
- [x] 浏览器截图/交互、`skill.run`、`shell.exec`、GitHub Actions logs 已通过 tool metadata 标记为 `background_candidate`。
- [x] `GET /api/v1/agent/background-tasks/overview` 已提供后台任务恢复 UI 所需的数据面：状态计数、最近任务、可重放任务、后台候选工具。
- [x] `POST /api/v1/agent/background-tasks/{task_id}/replay` 已支持失败/中断任务安全重放。
- [x] 通道来源中直接调用 `background_candidate` 工具时，runtime 会自动改写为 `task.start`，API 直接执行保持前台语义。

#### 17.5.4 ToolFallbackPolicy

目标：工具失败后不要只把错误丢回模型，而是由框架提供可解释、可恢复、可降级的策略。

建议错误分类：

```text
directory_as_file
path_not_found
permission_denied
tool_unavailable
dependency_missing
auth_missing
network_failed
timeout
invalid_payload
policy_denied
```

典型 fallback：

- `filesystem.read_file` 遇到目录：提示或自动建议 `filesystem.list_dir`。
- 路径不存在：先 `filesystem.list_dir` 父目录，帮助模型修正路径。
- Playwright/浏览器缺失：返回明确安装命令和当前依赖状态。
- GitHub CLI 未登录：提示 `gh auth status` / `gh auth login`。
- 网络失败：检查代理环境和目标连通性。
- SQL schema 不支持某方言字段：降级返回表名和列名基础信息。
- 权限拒绝：返回当前 policy snapshot 中相关字段，避免模型反复尝试同一个被拒绝动作。

实现要求：

- fallback 策略放在 `xbot.agent.tools.fallback_policy`，不要写死在 `AgentRuntime`。
- `ToolExecutor` 捕获异常后生成结构化 `ToolError`，再交给 fallback policy 决定是否建议新工具调用。
- 对自动重试设置上限和审计事件，避免无限循环。
- fallback 结果必须回填给 LLM，但不能直接把内部工具 JSON 暴露给最终用户。

当前实现状态：

- [x] 工具失败结果已包含 `error_type` 和 `fallback`。
- [x] `fallback.suggested_tool` 为只读工具时，runtime 会自动执行一次并写入 `fallback.auto_result`。
- [x] 自动 fallback 会记录 `tool.fallback_completed` 审计事件。
- [x] timeout fallback 会建议 `task.start`，且仅当原工具为只读工具时自动转入后台任务。
- [x] 写入、删除、shell、外部网络等高风险 fallback 只给建议，不自动执行。

#### 17.5.5 四阶段落地顺序

1. [x] 新增 `EnvironmentProvider`，先实现 `environment.snapshot` 和 `environment.which`。
2. [x] 在 Agent prompt 中加入环境探测规则，让模型遇到运行时能力问题先调用 environment 工具。
3. [x] 新增 `ToolError` 结构和 `ToolFallbackPolicy`，先覆盖目录读取、路径不存在、依赖缺失、GitHub 未登录。
4. [x] 新增 `BackgroundTaskManager` 内存实现和 API，先支持本进程后台任务。
5. [x] 将浏览器截图、浏览器 session actions、GitHub Actions logs、长 skill.run 标记为可后台执行。
6. [x] 接入 reply router：通道消息触发后台任务后，完成时主动回发最终结果。
7. [x] 将后台任务状态和事件持久化到 PostgreSQL，内存实现只保留给 dev/test fallback。

### 17.6 终端 Agent 对话模式规划

下一阶段需要补一个终端交互模式，让用户不经过微信、不经过 HTTP API 页面，直接在命令行里和同一套 `AgentRuntime` 对话。这更接近 Codex/Hermes 的使用方式：终端是一个一等入口，既能聊天，也能调用工具、显示工具进度、继续上下文和管理后台任务。

它不是新的 Agent，也不是单独实现一套工具系统，而是复用当前后端已有能力：

```text
terminal user
  -> xbot cli chat / xbot tui
  -> AgentRuntime.run_task / continue_task
  -> ToolRegistry / ToolExecutor / BackgroundTaskManager
  -> filesystem / shell / browser / git / github / skill / plugin tools
  -> terminal renderer
```

#### 17.6.1 目标

终端对话模式要解决这些问题：

- 不启动微信通道也能直接测试 Agent 能力。
- 不需要前端页面，也能在服务器/NAS/Windows 控制台里管理和调试。
- 长任务、工具调用、后台任务能在终端显示进度和状态。
- 插件、skill、工具 provider 调试可以直接在本地终端完成。
- 终端会话和微信会话使用同一套 Agent 记忆、策略、工具和审计表。

第一阶段目标是 CLI chat，不追求复杂全屏 UI；第二阶段再做 TUI。

#### 17.6.2 交互形态

第一阶段命令：

```text
python -m xbot.cli.main chat
python -m xbot.cli.main agent chat
xbot chat
```

交互示例：

```text
xbot> 你好
assistant> 你好，我是 xbot Agent。

xbot> 列出 plugins 目录
tool filesystem.list_dir {"path":"plugins"}
assistant> 当前 plugins 目录包含：agent_chat、echo、manage_plugin、image_gen。

xbot> /tools
xbot> /tasks
xbot> /exit
```

建议内置命令：

```text
/help       查看终端命令
/exit       退出
/status     显示 runtime、LLM、storage、toolset 状态
/tools      列出当前可见工具
/tasks      列出后台任务
/task ID    查看后台任务详情
/replay ID  重放失败后台任务
/memories   查看最近 Agent 记忆
/clear      清空当前终端屏幕，不删除会话
/new        开启新的终端会话
```

#### 17.6.3 输出规则

终端输出可以比微信更透明，但仍要分层：

- 默认只显示用户输入、最终回答和简短工具状态。
- `--verbose` 模式显示工具名称、耗时、状态、错误摘要。
- `--debug` 模式显示完整工具 payload/result 摘要和 LLM raw id。
- 不在终端默认输出密钥、token、cookie、完整环境变量。
- 工具调用 JSON 不作为“助手回答”展示，而是作为事件行展示。

推荐展示：

```text
● user
  列出 skill 目录

◇ tool filesystem.list_dir  completed  12ms

● assistant
  当前 skill 有：code_assistant、微信发送skill、dakka-image-generator。
```

#### 17.6.4 会话和上下文

终端对话应该有独立 source：

```text
source = "terminal:local:<session_id>"
```

规则：

- 每次 `xbot chat` 默认创建一个新的 terminal conversation。
- 可用 `--session <id>` 继续指定会话。
- 可用 `--cwd <path>` 指定工作目录，影响 Agent workspace root 或输入上下文。
- 终端消息进入 conversation store，和微信消息一样可以被压缩摘要。
- Agent 输入要带入 terminal metadata：cwd、用户名、主机名、shell、Python venv、当前 git repo。

建议输入模板：

```text
Terminal message received.
platform: terminal
adapter: cli
session_id: ...
cwd: ...
shell: powershell
content: ...
```

#### 17.6.5 工具和权限

终端模式的工具可见性应独立于微信私聊/群聊：

```toml
[agent.toolsets]
terminal = [
  "core",
  "filesystem",
  "filesystem_write",
  "skill",
  "shell",
  "environment",
  "task",
  "browser",
  "database",
  "git",
  "plugin"
]
```

默认策略：

- `developer` 模式：可读文件、可写 workspace、shell 仍按 `XBOT_AGENT_ALLOW_SHELL` 控制。
- `admin` 模式：终端可使用所有已注册工具，但继续写审计日志。
- 终端模式不能因为是本机就绕过 `PolicyEngine`。
- 删除文件、数据库写入、系统命令等危险行为继续走现有 policy。

#### 17.6.6 后台任务

终端对话要和后台任务系统打通：

- Agent 启动长任务后，终端立即显示 task id。
- 后台任务完成时，如果当前终端还活着，可以打印完成事件。
- 如果终端已经退出，结果仍写入 PostgreSQL，用户下次 `/tasks` 可查看。
- `/replay ID` 调用现有 replay API/Runtime 方法。

终端里长任务不应该阻塞输入循环。可以先用轮询，后续再做事件订阅。

#### 17.6.7 实现建议

第一阶段实现轻量 CLI，不引入复杂 TUI 依赖：

- 在 `src/xbot/cli/main.py` 增加 `chat` 命令。
- 复用 `build_context(load_settings())` 创建完整 runtime。
- 启动 engine，但可以选择不启动 adapters：第一版建议增加 `runtime profile` 或 `chat` 参数控制。
- 读取 stdin 循环，调用 `ctx.agent.run_task()`。
- 输出 final answer。
- 捕获 Ctrl+C，优雅 stop engine。

模块建议：

```text
src/xbot/cli/chat.py
  -> TerminalChatSession
  -> TerminalRenderer
  -> slash command parser
```

后续 TUI 可以再引入：

- `rich`：彩色输出、表格、panel、progress。
- `prompt_toolkit`：历史记录、补全、多行输入。
- `textual`：全屏 TUI，任务列表、工具事件、日志面板。

#### 17.6.8 落地顺序

1. [x] 新增 `xbot chat` / `python -m xbot.cli.main chat` 命令。
2. [x] 增加 `TerminalChatSession`，复用 `AgentRuntime`。
3. [x] 增加 terminal source/context 输入模板。
4. [x] 增加 terminal toolset 可见性配置。
5. [x] 支持 `/help`、`/exit`、`/status`、`/tools`、`/tasks`、`/task`、`/replay`、`/events`、`/logs`、`/new`。
6. [x] 工具事件简要显示，默认隐藏内部 JSON。
7. [x] 后台任务完成事件在终端中可见。
8. [x] 支持 `--session` 继续会话和 `--cwd` 指定工作目录。
9. [x] 第二阶段升级为 rich/prompt_toolkit TUI-lite：彩色面板、表格、spinner、命令补全和历史记录；Windows 下默认关闭 prompt_toolkit 输入以保证中文 IME，可用 `--fancy-input` 手动启用。
10. [x] 第三阶段补终端内事件回看：`/events [n]` 查看最近 Agent 事件，`/logs [n]` 同时查看 Agent 事件和后台任务事件。
11. [x] 第六阶段做全屏 Textual UI 第一版：`chat --tui` 提供左侧会话、右侧工具事件、底部输入框；`xbot` 无参数默认进入中文输入兼容性更好的原生输入普通终端对话。
12. [x] Hermes 对齐第一阶段：新增 `TerminalDisplayState` 和 `ToolProgressRenderer`，把零散事件打印改成 activity 面板、工具历史、耗时和最终回答面板。
13. [x] Hermes 对齐第二阶段第一版：OpenAI-compatible LLM provider 增加 `stream()`，Runtime 仅在 `terminal:` source 发布不落库的 `llm.delta`，终端 response box 支持自然语言流式输出，并屏蔽 tool-call JSON。
14. [x] Hermes 对齐第三阶段第一版：启动页显示模型、工具、插件、skill 概览；activity 面板支持 `--verbose` 工具输入摘要和 `--debug` 工具输出摘要；终端任务执行中按 `Ctrl+C` 会尝试取消当前任务并保留会话。
15. [x] Hermes 对齐第四阶段第一版：`--fancy-input` 使用 prompt_toolkit 多行输入、历史/补全、`patch_stdout` 输出保护和底部状态栏；Windows 默认仍保留原生输入。
16. [x] Hermes 对齐第五阶段第一版：新增 `xbot chat-bridge` JSONL stdin/stdout 协议入口，作为独立 TUI/Web/PTY 前端进程接入 AgentRuntime 的基础。
17. [x] Hermes 状态栏增强：普通 CLI 每轮回复后显示模型、上下文已用/窗口、百分比进度条、本轮耗时和 LLM 耗时；`--verbose` 才显示 activity 明细面板，减少默认对话区噪音。
18. [ ] Hermes 对齐第六阶段：基于 `chat-bridge` 实现真正独立 UI 进程的 TUI/Web/PTY 前端。

#### 17.6.9 Hermes 参考后的终端显示架构

Hermes 的终端体验不是简单 `print + input`，而是分层 UI：

- 输入层：经典 CLI 使用 `prompt_toolkit.TextArea`，支持多行、历史、补全和动态高度；Windows 中文输入法场景下需要保留原生输入 fallback。
- 输出层：Rich/ANSI 输出统一经过安全打印通道，用户、assistant、system、activity 分层展示，避免后台日志、工具输出和输入区互相覆盖。
- 状态层：模型、耗时、上下文、后台任务、当前工具以启动页能力卡片、状态栏或 activity 面板呈现，不作为普通日志刷屏。
- 上下文状态：已用量优先使用 OpenAI-compatible 响应中的 `usage.total_tokens`，没有 usage 时按输入/输出字符数粗估；窗口总量不是所有接口都会返回，因此优先读取 `agent.llm.context_window_tokens` / `XBOT_LLM_CONTEXT_WINDOW_TOKENS`，未配置时按模型名兜底。
- 工具层：工具开始只更新当前状态；工具完成后才写入简短历史。`--verbose` 展示工具输入摘要，`--debug` 展示工具输出摘要，完整 payload/result 仍通过 `/events` 查看。
- 流式层：LLM provider 需要原生 delta 回调。终端接收 `llm.delta` 后写入 response box，同时过滤 reasoning 标签和中间 tool-call JSON；当前第一版只对 `terminal:` source 开启，且 `llm.delta` 不写入事件表，避免数据库被 token 级事件刷屏。
- 进程分离层：`chat-bridge` 用 JSONL stdin/stdout 暴露 `ready`、`agent_event`、`background_task`、`final` 等事件，后续独立 TUI/Web/PTY 只负责 UI，AgentRuntime 继续由后端进程负责。

xbot 的落地策略：

```text
AgentRuntime events
  -> TerminalDisplayState
  -> ToolProgressRenderer
  -> Activity panel / response panel

LLMProvider.stream
  -> AgentRuntime llm.delta events
  -> TerminalRenderer streaming response box

External UI process
  -> xbot chat-bridge JSONL
  -> AgentRuntime events / final output
```

第一步已完成非流式显示优化：每轮输出一个 activity 面板，聚合 thinking、工具调用、耗时和错误摘要；保留 `/events`、`/logs` 作为完整事件回看。第二步已完成终端自然语言流式第一版：LLM delta 先经过安全判断，疑似 JSON/tool-call 的内容不展示，最终仍由 planner 解析后输出干净回复，并兼容累计/重叠 stream chunk 去重。第三步已完成启动概览、工具摘要分层和当前任务取消。第四步已完成 `--fancy-input` 的多行输入、状态栏和输出保护。第五步已完成 JSONL bridge，后续真正独立 UI 进程应基于该协议实现。

## 18. Skill 体系

Skill 是给智能体使用的能力包，偏“说明、流程、约束和工具编排”，不是长期运行的业务模块。

Skill 与 Plugin 的区别：

- Plugin 面向事件和业务扩展，常驻加载，可响应消息。
- Skill 面向智能体任务，按需加载，用来指导 agent 如何完成某类任务。
- Plugin 可以提供工具。
- Skill 可以声明需要哪些工具和插件能力。

Skill 目录示例：

```text
skills/code_assistant/
  skill.toml
  SKILL.md
```

`skill.toml`：

```toml
name = "code_assistant"
version = "0.1.0"
description = "Guide agent to inspect, edit, and verify code changes."

[tools]
required = [
  "filesystem.read_file",
  "filesystem.write_file",
  "shell.exec"
]
```

`SKILL.md` 存放该 skill 的执行规则、工作流和注意事项。

## 19. Plugin 与 Skill 的关系

框架同时支持 plugin 和 skill。

Plugin 适合：

- 消息事件处理。
- 指令系统。
- 平台业务集成。
- 长期运行的后台任务。
- 对外提供可复用工具。

Skill 适合：

- 代码修改流程。
- 运维排障流程。
- 数据分析流程。
- 内容生成流程。
- 特定领域任务指引。

建议统一注册：

```text
PluginManager
  -> load plugins
  -> expose plugin hooks
  -> expose plugin tools

SkillManager
  -> load skills
  -> expose skill instructions
  -> expose skill metadata

AgentRuntime
  -> select skills
  -> call tools
  -> call plugin tools
```

## 20. Agent 权限模型

Agent 可以具备接近本地开发助手的能力，包括读取系统信息、访问文件、修改代码、删除文件、执行命令、访问网络、查询数据库和调用插件。

这些能力必须通过统一权限模型控制。Agent 不直接访问系统资源，所有操作都经过：

```text
AgentRuntime
  -> ToolExecutor
  -> PolicyEngine
  -> WorkspaceGuard
  -> Real Tool
```

### 20.1 权限模式

框架提供三档权限模式：

```toml
[agent]
mode = "safe"      # 只读模式，适合生产环境
# mode = "developer" # 开发模式，可改 workspace，可执行常用命令
# mode = "admin"     # 最高权限模式，可访问全系统
```

`safe` 模式：

- 允许读取框架状态。
- 允许读取明确授权目录内的文件。
- 禁止写文件。
- 禁止删除文件。
- 禁止执行 shell。
- 禁止数据库写操作。
- 禁止访问 workspace 外部目录。

`developer` 模式：

- 允许读取 workspace 内文件。
- 允许创建和修改 workspace 内文件。
- 默认禁止删除文件，或删除操作需要审批。
- 允许执行常用开发命令。
- 允许访问网络。
- 禁止访问敏感系统目录。
- 禁止默认访问 workspace 外部目录。

`admin` 模式：

- 允许访问所有目录。
- 允许创建、修改、删除文件。
- 允许执行系统命令。
- 允许安装依赖。
- 允许访问网络。
- 允许数据库读写。
- 允许修改框架代码和插件代码。
- 默认不需要危险操作审批，但必须记录审计日志。

### 20.2 最高权限配置

如果用户明确需要让 Agent 拿到最高权限，可以配置：

```toml
[agent]
enabled = true
mode = "admin"

[agent.workspace]
allow_all_filesystem = true
roots = ["*"]
deny = []
allow_outside_workspace = true

[agent.tools]
system_info = true
file_read = true
file_write = true
file_delete = true
shell_exec = true
network = true
database_query = true
database_write = true
plugin_call = true
skill_run = true

[agent.approval]
dangerous_tools = false
outside_workspace = false
delete_files = false
shell_exec = false
database_write = false
```

该模式下 Agent 可以访问整个系统。这个能力是有意设计的，但必须显式开启，不能作为默认行为。

### 20.3 硬禁用开关

为了避免生产环境误开启最高权限，需要提供环境变量硬禁用：

```env
XBOT_AGENT_ADMIN_MODE_ALLOWED=false
```

当该环境变量为 `false` 时，即使配置文件写了 `mode = "admin"`，框架也必须拒绝启动或自动降级为 `developer`，并输出明确错误日志。

建议行为：

```text
XBOT_AGENT_ADMIN_MODE_ALLOWED=false + mode=admin
  -> startup failed
  -> log: Agent admin mode is disabled by environment policy.
```

### 20.4 Workspace 规则

非 admin 模式下，文件访问必须受 workspace 限制。

示例：

```toml
[agent.workspace]
roots = [
  "./xbot-next",
  "./plugins"
]
deny = [
  "C:/Windows",
  "C:/Users/*/.ssh",
  "C:/Users/*/AppData",
  "/etc",
  "/root",
  "/home/*/.ssh"
]
allow_outside_workspace = false
```

路径检查规则：

- 所有路径先规范化为绝对路径。
- 命中 `deny` 的路径永远拒绝。
- 非 admin 模式下，目标路径必须位于 `roots` 内。
- `..` 路径逃逸必须被规范化后重新检查。
- 符号链接需要解析真实路径后检查。
- 删除目录、递归删除、批量移动都属于危险操作。

### 20.5 工具风险等级

每个工具必须声明风险等级。

```text
read       只读能力
write      写文件、改配置
execute    执行命令
network    访问外部网络
dangerous  删除、移动、安装依赖、改系统配置等高风险操作
```

示例：

- `system.info`: `read`
- `filesystem.read_file`: `read`
- `filesystem.write_file`: `write`
- `filesystem.create_file`: `write`
- `filesystem.delete_file`: `dangerous`
- `shell.exec`: `execute`
- `shell.install_dependency`: `dangerous`
- `database.query`: `read`
- `database.execute`: `dangerous`

### 20.6 审批策略

审批策略由配置控制：

```toml
[agent.approval]
dangerous_tools = true
outside_workspace = true
delete_files = true
shell_exec = false
database_write = true
```

规则：

- `safe` 模式默认拒绝危险操作。
- `developer` 模式默认审批危险操作。
- `admin` 模式默认不审批危险操作。
- 即使不审批，也必须记录审计日志。

后续前端可以基于审批事件实现“允许 / 拒绝”操作。

### 20.7 审计日志

Agent 所有工具调用都必须写审计日志。

至少记录：

- task id
- user id 或 source
- tool name
- input 摘要
- risk level
- policy decision
- touched files
- command
- start time
- end time
- success / failure
- error message

审计日志写入 `agent_events` 表。admin 模式不能关闭审计。

### 20.8 API 和 CLI

后续前端和 CLI 都可以修改 Agent 权限。

API：

```text
GET  /api/v1/agent/policy
PUT  /api/v1/agent/policy
POST /api/v1/agent/policy/validate
```

CLI：

```text
xbot agent policy show
xbot agent policy set mode=developer
xbot agent policy set file_write=false
xbot agent workspace add "D:/project"
xbot agent workspace deny "C:/Users/*/.ssh"
```

修改到 `admin` 模式时必须有明确确认流程。CLI 至少要求 `--confirm-admin-mode` 参数。

## 21. Agent 记忆与自动压缩

Agent 需要记忆系统，但不能把所有上下文无限堆进模型。记忆系统要分层存储、按需检索、自动压缩，并且支持遗忘和审计。

### 21.1 记忆分层

建议分四层：

```text
working memory
  -> 当前任务上下文，短期有效

episodic memory
  -> 任务过程、用户对话、工具调用轨迹

semantic memory
  -> 被总结后的稳定知识，例如项目结构、用户偏好、长期规则

artifact memory
  -> 文件、代码片段、补丁、日志、生成物引用
```

`working memory`：

- 存当前任务的 prompt、计划、最近消息、最近工具结果。
- 生命周期通常只在一个 task 内。
- 超过 token 或事件数量后自动压缩。

`episodic memory`：

- 存 agent 做过什么。
- 适合追踪任务历史、复盘和继续任务。
- 例如“第 12 次工具调用修改了 plugins/foo/main.py”。

`semantic memory`：

- 存稳定结论。
- 例如“用户希望默认使用 PostgreSQL”、“xbot-next 是新框架，不迁移旧代码”。
- 由压缩器从 episodic memory 中提炼。

`artifact memory`：

- 不直接保存大文件全文。
- 保存路径、hash、摘要、版本、关联 task。
- 大内容放文件系统或对象存储，数据库只保存引用。

### 21.2 记忆写入规则

不是所有内容都进入长期记忆。

默认写入：

- 用户明确表达的长期偏好。
- 架构决策。
- 已完成任务摘要。
- 关键错误和修复方案。
- 插件和 skill 的使用经验。
- 重要文件变更摘要。

默认不写入：

- 密码、token、cookie、私钥。
- 大段日志全文。
- 临时命令输出。
- 可从文件系统重新读取的完整源码。
- 用户明确要求不记住的内容。

敏感信息检测失败时，应宁可不写入长期记忆。

### 21.3 自动压缩

Agent 需要 `MemoryCompressor`，用于把长上下文压缩成结构化摘要。

触发条件：

- 当前 task 事件数超过阈值。
- 当前上下文 token 估算超过阈值。
- 工具输出过长。
- task 完成。
- 定时后台维护。

压缩输出应该是结构化数据，而不是普通自然语言段落。

建议格式：

```json
{
  "summary": "完成了 xbot-next 后端框架设计文档更新。",
  "decisions": [
    "默认主存储使用 PostgreSQL",
    "Agent 支持 safe/developer/admin 三档权限",
    "Plugin 和 Skill 分离"
  ],
  "changed_files": [
    "xbot-next/docs/backend-framework-design.md"
  ],
  "open_questions": [
    "具体 LLM provider 尚未确定"
  ],
  "next_actions": [
    "搭建 pyproject.toml 和 src/xbot 基础骨架"
  ]
}
```

### 21.4 检索策略

Agent 不应该每次加载所有记忆。

建议检索顺序：

```text
current task context
  -> pinned memories
  -> recent episodic memory
  -> semantic memory search
  -> artifact references
```

检索方式：

- PostgreSQL 普通索引用于 task、user、source、time、tags。
- 向量索引用于语义检索。第一版可以先预留接口，不强制实现。
- 关键词索引用于文件名、插件名、skill 名。

第一版可以先做 PostgreSQL 检索，后续再接向量库。

### 21.5 遗忘与覆盖

必须支持删除和修正记忆。

API：

```text
GET    /api/v1/agent/memories
POST   /api/v1/agent/memories
DELETE /api/v1/agent/memories/{memory_id}
POST   /api/v1/agent/memories/compact
```

规则：

- 用户可以删除指定记忆。
- 用户可以清空某个 source 的记忆。
- semantic memory 可以被新事实覆盖，但旧版本应保留审计记录。
- 敏感记忆一旦发现，应立即删除或标记为 redacted。

### 21.6 数据表

建议新增表：

- `agent_memories`
  - id
  - scope
  - kind
  - source
  - content_json
  - summary
  - tags_json
  - importance
  - expires_at
  - created_at
  - updated_at
- `agent_memory_links`
  - id
  - memory_id
  - task_id
  - artifact_id
  - relation
  - created_at
- `agent_artifacts`
  - id
  - task_id
  - kind
  - path
  - content_hash
  - summary
  - metadata_json
  - created_at

`kind` 建议值：

- `working`
- `episodic`
- `semantic`
- `artifact`
- `preference`
- `decision`

### 21.7 配置

```toml
[agent.memory]
enabled = true
store = "postgresql"
auto_compress = true
max_working_events = 50
max_tool_output_chars = 12000
semantic_memory = true
vector_search = false
retention_days = 180

[agent.memory.redaction]
enabled = true
patterns = [
  "password",
  "token",
  "secret",
  "api_key",
  "private_key"
]
```

### 21.8 实现建议

模块：

```text
agent/memory.py
  -> MemoryStore
  -> MemoryRetriever
  -> MemoryWriter

agent/compression.py
  -> MemoryCompressor
  -> ToolOutputCompressor
  -> TaskSummaryCompressor
```

第一版最小实现：

- task 事件落库。
- task 完成时生成摘要。
- 超长工具输出压缩保存。
- 支持查询最近 task memory。
- 支持手动触发 compact。

后续增强：

- 向量检索。
- 用户偏好自动提取。
- 项目知识图谱。
- 跨 task 规划记忆。

## 22. 存储设计

默认 PostgreSQL。

第一版需要表：

- `plugins`
  - name
  - version
  - enabled
  - path
  - created_at
  - updated_at
- `messages`
  - id
  - platform
  - adapter
  - conversation_id
  - sender_id
  - type
  - content
  - raw_json
  - created_at
- `message_envelopes`
  - id
  - trace_id
  - dedupe_key
  - message_id
  - delivery_attempts
  - available_at
  - headers_json
  - created_at
- `dead_letters`
  - id
  - trace_id
  - queue_name
  - payload_json
  - error
  - attempts
  - created_at
- `conversations`
  - id
  - platform
  - adapter
  - scope
  - raw_id
  - title
  - created_at
  - updated_at
- `conversation_members`
  - id
  - conversation_id
  - user_id
  - display_name
  - role
  - joined_at
- `conversation_messages`
  - id
  - conversation_id
  - message_id
  - sender_id
  - type
  - content
  - created_at
- `conversation_states`
  - id
  - conversation_id
  - namespace
  - value_json
  - updated_at
- `conversation_summaries`
  - id
  - conversation_id
  - summary
  - from_message_id
  - to_message_id
  - created_at
- `config_items`
  - key
  - value_json
  - updated_at
- `skills`
  - name
  - version
  - enabled
  - path
  - created_at
  - updated_at
- `agent_tasks`
  - id
  - status
  - source
  - input
  - result
  - created_at
  - updated_at
- `agent_events`
  - id
  - task_id
  - type
  - content
  - created_at
- `agent_memories`
  - id
  - scope
  - kind
  - source
  - content_json
  - summary
  - tags_json
  - importance
  - expires_at
  - created_at
  - updated_at
- `agent_memory_links`
  - id
  - memory_id
  - task_id
  - artifact_id
  - relation
  - created_at
- `agent_artifacts`
  - id
  - task_id
  - kind
  - path
  - content_hash
  - summary
  - metadata_json
  - created_at

存储层通过 repository 访问，不允许 API 层直接操作数据库。

### 22.1 Migration 策略

生产和共享环境必须使用 Alembic 管理数据库结构，不能直接依赖 `Base.metadata.create_all`。

当前工具链：

- `alembic.ini`：Alembic 主配置。
- `migrations/env.py`：读取 `xbot` 配置并使用 `postgresql+asyncpg` 异步引擎执行迁移。
- `migrations/versions/0001_initial_schema.py`：初始 schema，覆盖当前 SQLAlchemy metadata 中的核心表。
- `tests/unit/core/test_migrations.py`：校验 migration 配置存在，并约束初始 migration 覆盖模型表。

CLI 命令：

```text
xbot db-init          # 等价于 xbot db-upgrade head
xbot db-bootstrap     # 检测并自动创建 database/role，然后升级 schema
xbot db-upgrade       # 升级到 head
xbot db-upgrade <rev> # 升级到指定 revision
xbot db-current       # 查看当前数据库 revision
xbot db-downgrade     # 默认回退一个 revision
```

规则：

- 新增表、字段、索引、约束时必须新增 Alembic revision。
- `Storage.init_schema()` 只保留给测试或本地临时环境，不作为正式部署路径。
- API 层和 service 层不直接执行 migration。
- 应用启动阶段会执行 `StorageBootstrap`，默认检测 PostgreSQL 并在配置允许时自动创建 database/role。
- 自动创建 database/role 需要 `XBOT_ADMIN_DATABASE_URL` 或 `[storage].admin_url`。
- 如果目标 role 已存在但密码和 `XBOT_DATABASE_URL` 不一致，框架会拒绝自动覆盖已有 role 密码。
- 启动阶段默认自动执行 Alembic upgrade，可用 `[storage].run_migrations_on_startup = false` 关闭。

## 23. 配置设计

默认配置文件：`configs/xbot.toml`

```toml
[xbot]
name = "xbot"
timezone = "Asia/Shanghai"
debug = false

[server]
host = "0.0.0.0"
port = 8080

[storage]
type = "postgresql"
url = "postgresql+asyncpg://xbot:xbot@192.168.6.19:5433/xbot"
auto_bootstrap = true
create_database = true
create_role = true
run_migrations_on_startup = true

[queue]
type = "memory"
redis_url = "redis://192.168.6.41:6379/15"
main_queue = "xbot:messages"
reply_queue = "xbot:replies"
event_queue = "xbot:events"
agent_task_queue = "xbot:agent_tasks"
dead_letter_queue = "xbot:dead_letters"

[queue.retry]
max_attempts = 3
initial_delay_seconds = 2
max_delay_seconds = 60
backoff = "exponential"

[conversation]
enabled = true
store = "postgresql"
default_scope = "private"

[conversation.context]
recent_messages = 20
max_chars = 16000
auto_summarize = true
summary_every_messages = 50

[conversation.concurrency]
per_conversation_serial = true
max_active_conversations = 1000

[runtime.concurrency]
max_message_tasks = 100
max_plugin_tasks = 50
max_agent_tasks = 5
max_tool_tasks = 20
sync_worker_threads = 8

[runtime.timeout]
message_seconds = 60
plugin_seconds = 30
tool_seconds = 120
agent_task_seconds = 1800
http_seconds = 30

[plugins]
directory = "plugins"
auto_load = true

[skills]
directory = "skills"
auto_load = true

[agent]
enabled = true
mode = "developer"
workspace = "."
allow_shell = false
allow_file_write = true

[agent.workspace]
allow_all_filesystem = false
roots = ["."]
deny = [
  "C:/Windows",
  "C:/Users/*/.ssh",
  "C:/Users/*/AppData",
  "/etc",
  "/root",
  "/home/*/.ssh"
]
allow_outside_workspace = false

[agent.approval]
dangerous_tools = true
outside_workspace = true
delete_files = true
shell_exec = false
database_write = true

[agent.memory]
enabled = true
store = "postgresql"
auto_compress = true
max_working_events = 50
max_tool_output_chars = 12000
semantic_memory = true
vector_search = false
retention_days = 180

[agent.memory.redaction]
enabled = true
patterns = [
  "password",
  "token",
  "secret",
  "api_key",
  "private_key"
]

[agent.llm]
enabled = false
provider = "openai_compatible"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
context_window_tokens = 128000
timeout_seconds = 60
max_tokens = 2000
temperature = 0.2

[adapters.web]
enabled = true
```

配置优先级：

```text
default values
  < config file
  < environment variables
  < CLI arguments
```

## 24. 管理 API

API 版本从 `/api/v1` 开始。

第一版 API：

```text
GET    /api/v1/system/status
GET    /api/v1/bot/status
POST   /api/v1/bot/start
POST   /api/v1/bot/stop
POST   /api/v1/bot/restart

GET    /api/v1/adapters
POST   /api/v1/adapters/{name}/enable
POST   /api/v1/adapters/{name}/disable

GET    /api/v1/plugins
POST   /api/v1/plugins/{name}/enable
POST   /api/v1/plugins/{name}/disable
POST   /api/v1/plugins/reload

GET    /api/v1/skills
POST   /api/v1/skills/{name}/enable
POST   /api/v1/skills/{name}/disable
POST   /api/v1/skills/reload

POST   /api/v1/agent/tasks
GET    /api/v1/agent/tasks/{task_id}
POST   /api/v1/agent/tasks/{task_id}/continue
POST   /api/v1/agent/tasks/{task_id}/cancel
GET    /api/v1/agent/tools
GET    /api/v1/agent/llm/status
POST   /api/v1/agent/tools/{tool_name}/execute
GET    /api/v1/agent/policy
PUT    /api/v1/agent/policy
POST   /api/v1/agent/policy/validate
GET    /api/v1/agent/memories
POST   /api/v1/agent/memories
DELETE /api/v1/agent/memories/{memory_id}
POST   /api/v1/agent/memories/compact

POST   /api/v1/messages/simulate
GET    /api/v1/messages/recent

GET    /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}
GET    /api/v1/conversations/{conversation_id}/messages
GET    /api/v1/conversations/{conversation_id}/state/{namespace}
PUT    /api/v1/conversations/{conversation_id}/state/{namespace}

GET    /api/v1/config
```

`/api/v1/messages/simulate` 用于第一版在没有真实平台 adapter 的情况下跑通消息处理。

## 25. CLI

第一版 CLI：

```text
xbot init
xbot run
xbot status
xbot db-bootstrap
xbot db-init
xbot db-upgrade
xbot db-current
xbot db-downgrade
xbot plugin list
xbot plugin enable <name>
xbot plugin disable <name>
xbot skill list
xbot agent run "<task>"
xbot agent policy show
xbot agent policy set mode=developer
xbot agent memory list
xbot agent memory compact
```

CLI 调用同一套 service，不另写业务逻辑。

## 26. MVP 里程碑

### M1: 项目骨架

- `pyproject.toml`
- `src/xbot`
- 配置加载
- 日志初始化
- async-first 基础约束
- FastAPI app 可启动
- `/api/v1/system/status`

### M2: 运行时

- `XBotEngine`
- 生命周期管理
- 并发限制配置
- 超时配置
- 运行状态查询
- `/api/v1/bot/status`
- start/stop/restart API

### M3: 消息模型和 WebAdapter

- 标准 `Message`
- 标准 `Reply`
- MessageEnvelope
- DedupeService
- MessageConsumer
- `BaseAdapter`
- `WebAdapter`
- simulate message API
- recent message API

### M3.5: 会话系统

- Conversation models
- ConversationManager
- SessionStore
- ContextWindow
- conversations API

### M4: 插件系统

- `PluginBase`
- plugin manifest
- plugin loader
- plugin manager
- EchoPlugin
- 插件列表/启停 API

### M5: 消息闭环

- simulate text message
- pipeline dispatch
- queue publish / consume
- dedupe check
- conversation touch
- EchoPlugin 回复
- reply router
- recent messages API
- reply store

### M6: 存储

- PostgreSQL 初始化
- plugin 状态持久化
- message 记录持久化

### M7: Skill 和 Agent Runtime

- Skill manifest
- Skill loader
- ToolRegistry
- ToolExecutor
- AgentRuntime
- PolicyEngine
- WorkspaceGuard
- MemoryStore
- MemoryCompressor
- agent task API
- agent policy API
- agent memory API
- 文件读取工具
- 受控文件写入工具
- EchoPlugin 工具调用示例

完成 M1-M7 后，后端框架算第一版可运行。

## 27. 代码风格约束

- API 层不写业务逻辑。
- service 层不依赖 FastAPI Request。
- 核心运行时和 I/O 边界必须 async-first。
- 同步插件和同步工具必须通过 anyio 线程池隔离执行。
- 禁止在事件循环线程里执行阻塞式数据库、网络或长文件操作。
- plugin 不直接访问 FastAPI app。
- adapter 不直接调用插件。
- agent 不直接绕过 tool executor 操作系统资源。
- skill 不直接执行代码，只提供指令和工具需求。
- admin mode 也不能绕过审计日志。
- agent 长期记忆不能保存敏感凭据。
- 超长上下文必须通过压缩器处理，不能无限追加。
- storage 不泄漏 ORM model 到 API response。
- 所有外部输出使用 schemas。
- 所有跨模块数据使用明确模型，不传裸 dict，除非是 raw payload。

## 28. 与当前项目的关系

当前项目只作为功能参考：

- 多平台 adapter 思路。
- 插件管理思路。
- 消息队列和回复路由思路。
- 管理后台 API 能力清单。
- 二维码登录、联系人、文件管理、终端等后续功能参考。

新框架不继承旧命名：

- 框架名统一为 `xbot`。
- 配置段统一为 `[xbot]`。
- 队列默认使用 `xbot:*`。
- 数据库默认使用 PostgreSQL 的 `xbot` database。

如后续需要兼容旧项目，可以单独写 legacy adapter 或 migration tool。
