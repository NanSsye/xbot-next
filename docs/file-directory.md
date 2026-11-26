# 文件目录说明

> 由 `pg dir` 维护：新增路径会追加，并把职责标为 `TODO`，需要人工或 Agent 补全；已删除的路径会自动移除。
> 职责列可以直接手工编辑，`pg dir` 会保留已填写的内容。
> 旧版 Hermes 第三方快照只登记目录，不追踪快照内部文件；新版依赖由发行清单和锁文件管理。
> 最后同步：2026-11-26

<!-- pg:dir:start -->
| 路径 | 类型 | 职责 |
|------|------|------|
| `.dockerignore` | 文件 | 排除本地状态、配置和构建缓存 |
| `.env.example` | 文件 | 无真实凭据的运行配置与独立部署示例 |
| `.env.local.example` | 文件 | 无真实凭据的本地开发环境变量示例 |
| `.gitignore` | 文件 | 排除凭据、本地状态与编译产物 |
| `.pgignore` | 文件 | 从目录说明中排除本地编译与检查缓存 |
| `CLAUDE.md` | 文件 | 项目级 Agent 规则（继承全局 SDD + 强制落盘规则） |
| `Dockerfile` | 文件 | 构建后端、内嵌 Hermes 和控制台镜像 |
| `LICENSE` | 文件 | 项目许可证和使用限制 |
| `README.md` | 文件 | 项目入口：安装、配置、使用和开发说明 |
| `alembic.ini` | 文件 | Alembic 迁移位置与日志配置 |
| `configs` | 目录 | 应用配置模板和固定依赖发行清单 |
| `configs/hermes-release.json` | 文件 | 固定内嵌 Hermes 版本、提交及源码归档 SHA-256 |
| `configs/xbot.toml` | 文件 | 后端运行、通道、任务与 Agent 的默认配置 |
| `data` | 目录 | 本地运行生成的应用状态、会话和产物，不纳入源码 |
| `docker-compose.yml` | 文件 | 运行预构建镜像、隔离数据库和 Redis，声明持久化挂载 |
| `docs` | 目录 | 人类可读文档 |
| `docs/backend-framework-design.md` | 文件 | 后端模块划分、运行时和数据边界设计 |
| `docs/changelog.md` | 文件 | 变更记录（pg log 维护） |
| `docs/docker-deployment.md` | 文件 | 镜像交付、独立初始化、访问范围与备份说明 |
| `docs/file-directory.md` | 文件 | 文件目录说明（pg dir 维护） |
| `docs/frontend-control-ui.md` | 文件 | 控制台功能、API 对接与本地构建说明 |
| `docs/hermes-agent-integration.md` | 文件 | 内嵌 Hermes 的版本、安装、配置、状态和回退说明 |
| `docs/product-knowledge-graph.md` | 文件 | 产品知识图谱的可读视图（pg update 自动生成，勿手改） |
| `docs/production-deployment.md` | 文件 | 独立生产部署流程与运维要求 |
| `docs/screenshots` | 目录 | README 使用的桌面 Web 演示截图 |
| `docs/screenshots/desktop-agent.png` | 文件 | Agent 会话、工具执行和产物示例 |
| `docs/screenshots/desktop-overview.png` | 文件 | 控制台运行总览和通道状态示例 |
| `docs/screenshots/desktop-wechat.png` | 文件 | 微信工作台、头像和出站回复示例 |
| `files` | 目录 | 本地运行生成的静态文件目录，不纳入源码 |
| `knowledge` | 目录 | 知识库根目录 |
| `knowledge/audit.jsonl` | 文件 | 图谱写入审计日志（谁/何时/来源/版本/diff） |
| `knowledge/graph` | 目录 | 产品知识图谱数据（唯一事实源） |
| `knowledge/graph/edges.jsonl` | 文件 | 图谱关系，一行一个 JSON |
| `knowledge/graph/nodes.jsonl` | 文件 | 图谱节点，一行一个 JSON |
| `knowledge/index` | 目录 | 检索索引（可随时用 pg index 重建，勿手改） |
| `migrations` | 目录 | Alembic 迁移环境及数据库版本脚本 |
| `migrations/README.md` | 文件 | 数据库迁移操作和版本说明 |
| `migrations/env.py` | 文件 | 加载 ORM 元数据并配置在线和离线迁移 |
| `migrations/script.py.mako` | 文件 | 生成 Alembic 迁移脚本的模板 |
| `migrations/versions` | 目录 | 应用数据库版本的升级与回退实现 |
| `migrations/versions/fresh_0001_initial_clean_schema.py` | 文件 | 创建不含微伴社区表的独立新库结构 |
| `patches` | 目录 | 旧 vendoring 流程的补丁队列 |
| `patches/hermes` | 目录 | 旧 Hermes 快照的补丁登记位置 |
| `patches/hermes/README.md` | 文件 | 历史同步脚本与补丁清单的维护约定 |
| `plugins` | 目录 | Xbot 可由框架发现、配置和加载的插件 |
| `plugins/GroupMonitor` | 目录 | 微信群成员监控和退群提醒插件 |
| `plugins/GroupMonitor/INDEX.md` | 文件 | 群成员监控的文档与使用入口索引 |
| `plugins/GroupMonitor/README.md` | 文件 | 微信群成员监控和退群提醒插件的配置和使用说明 |
| `plugins/GroupMonitor/config.toml` | 文件 | 微信群成员监控和退群提醒插件的默认配置 |
| `plugins/GroupMonitor/main.py` | 文件 | 同步群成员快照并触发退群提醒 |
| `plugins/GroupMonitor/plugin.toml` | 文件 | 声明微信群成员监控和退群提醒插件的注册信息和入口 |
| `plugins/GroupSocialGraph` | 目录 | 微信群友社交关系图插件 |
| `plugins/GroupSocialGraph/.gitignore` | 文件 | 排除微信群友社交关系图插件的本地配置或生成数据 |
| `plugins/GroupSocialGraph/README.md` | 文件 | 微信群友社交关系图插件的配置和使用说明 |
| `plugins/GroupSocialGraph/__init__.py` | 文件 | 微信群友社交关系图插件的包入口 |
| `plugins/GroupSocialGraph/config.toml` | 文件 | 微信群友社交关系图插件的默认配置 |
| `plugins/GroupSocialGraph/fonts` | 目录 | 群友关系图渲染使用的字体资源 |
| `plugins/GroupSocialGraph/main.py` | 文件 | 从群友互动聚合并渲染社交关系图 |
| `plugins/GroupSocialGraph/plugin.toml` | 文件 | 声明微信群友社交关系图插件的注册信息和入口 |
| `plugins/GroupWelcome` | 目录 | 微信群入群欢迎插件 |
| `plugins/GroupWelcome/README.md` | 文件 | 微信群入群欢迎插件的配置和使用说明 |
| `plugins/GroupWelcome/__init__.py` | 文件 | 微信群入群欢迎插件的包入口 |
| `plugins/GroupWelcome/config.toml` | 文件 | 微信群入群欢迎插件的默认配置 |
| `plugins/GroupWelcome/main.py` | 文件 | 根据 869 群系统消息生成入群欢迎卡片 |
| `plugins/GroupWelcome/plugin.toml` | 文件 | 声明微信群入群欢迎插件的注册信息和入口 |
| `plugins/JaysonChatSummary` | 目录 | 微信群聊 AI 总结卡片插件 |
| `plugins/JaysonChatSummary/README.md` | 文件 | 微信群聊 AI 总结卡片插件的配置和使用说明 |
| `plugins/JaysonChatSummary/__init__.py` | 文件 | 微信群聊 AI 总结卡片插件的包入口 |
| `plugins/JaysonChatSummary/config.toml` | 文件 | 微信群聊 AI 总结卡片插件的默认配置 |
| `plugins/JaysonChatSummary/data` | 目录 | 群聊总结插件的数据目录 |
| `plugins/JaysonChatSummary/group_chat_summary_card_template.html` | 文件 | 群聊总结的默认 HTML 卡片模板 |
| `plugins/JaysonChatSummary/group_chat_summary_card_template_forest.html` | 文件 | 群聊总结的森林主题卡片模板 |
| `plugins/JaysonChatSummary/group_chat_summary_card_template_light.html` | 文件 | 群聊总结的浅色主题卡片模板 |
| `plugins/JaysonChatSummary/group_chat_summary_card_template_retro.html` | 文件 | 群聊总结的复古主题卡片模板 |
| `plugins/JaysonChatSummary/group_chat_summary_card_template_sunset.html` | 文件 | 群聊总结的日落主题卡片模板 |
| `plugins/JaysonChatSummary/main.py` | 文件 | 读取群消息、生成 AI 总结并按需发送卡片 |
| `plugins/JaysonChatSummary/plugin.toml` | 文件 | 声明微信群聊 AI 总结卡片插件的注册信息和入口 |
| `plugins/PLUGIN_DEVELOPMENT_GUIDE.md` | 文件 | 插件清单、事件、运行上下文与测试约定 |
| `plugins/acode_remote` | 目录 | Telegram 私聊与 Codex 任务桥接插件 |
| `plugins/acode_remote/.gitignore` | 文件 | 排除Telegram 私聊与 Codex 任务桥接插件的本地配置或生成数据 |
| `plugins/acode_remote/README.md` | 文件 | Telegram 私聊与 Codex 任务桥接插件的配置和使用说明 |
| `plugins/acode_remote/config.example.toml` | 文件 | Telegram 与 Codex 任务桥接的无凭据配置示例 |
| `plugins/acode_remote/main.py` | 文件 | 选择已有 Codex 任务并在 Telegram 私聊转发消息 |
| `plugins/acode_remote/mcp_sender.example.toml` | 文件 | 发送工具使用的 SSH 和容器配置示例 |
| `plugins/acode_remote/mcp_server.py` | 文件 | 通过 stdio 暴露 Telegram 附件发送 MCP 工具 |
| `plugins/acode_remote/plugin.toml` | 文件 | 声明Telegram 私聊与 Codex 任务桥接插件的注册信息和入口 |
| `plugins/acode_remote/send_media.py` | 文件 | 在目标 Xbot 实例中读取配置并发送 Telegram 附件 |
| `plugins/agent_chat` | 目录 | 通道消息与 Agent 桥接插件 |
| `plugins/agent_chat/main.py` | 文件 | 处理私聊及群内提及后调用 Agent |
| `plugins/agent_chat/plugin.toml` | 文件 | 声明通道消息与 Agent 桥接插件的注册信息和入口 |
| `plugins/echo` | 目录 | 消息回显示例插件 |
| `plugins/echo/main.py` | 文件 | 回显命令用于插件框架冒烟检查 |
| `plugins/echo/plugin.toml` | 文件 | 声明消息回显示例插件的注册信息和入口 |
| `plugins/manage_plugin` | 目录 | 聊天内插件管理插件 |
| `plugins/manage_plugin/config.toml` | 文件 | 聊天内插件管理插件的默认配置 |
| `plugins/manage_plugin/main.py` | 文件 | 处理聊天命令以管理插件状态 |
| `plugins/manage_plugin/plugin.toml` | 文件 | 声明聊天内插件管理插件的注册信息和入口 |
| `plugins/wxsph_video` | 目录 | 短视频解析和音频转换插件 |
| `plugins/wxsph_video/main.py` | 文件 | 解析短视频链接并支持引用视频转 MP3 |
| `plugins/wxsph_video/plugin.toml` | 文件 | 声明短视频解析和音频转换插件的注册信息和入口 |
| `plugins/xhs_content` | 目录 | 小红书图文和视频解析插件 |
| `plugins/xhs_content/main.py` | 文件 | 识别小红书链接并通过原通道发送媒体 |
| `plugins/xhs_content/plugin.toml` | 文件 | 声明小红书图文和视频解析插件的注册信息和入口 |
| `pyproject.toml` | 文件 | Python 构建元数据、依赖安全下限、可选功能与测试配置 |
| `scripts` | 目录 | 安装、升级和源码归档准备脚本 |
| `scripts/install.ps1` | 文件 | Windows 首次安装，按锁文件准备 Hermes 和运行环境 |
| `scripts/install.sh` | 文件 | Unix 首次安装，按锁文件准备 Hermes 和运行环境 |
| `scripts/prepare_hermes.py` | 文件 | 校验固定归档并准备独立的内嵌 Hermes 源码目录 |
| `scripts/sync_hermes.py` | 文件 | 旧快照的校验与同步流程，归档校验函数由准备脚本复用 |
| `scripts/upgrade.ps1` | 文件 | Windows 更新工作副本和锁定的运行环境 |
| `scripts/upgrade.sh` | 文件 | Unix 更新工作副本和锁定的运行环境 |
| `skills` | 目录 | 随项目提供的通用和通道专用技能 |
| `skills/.agent` | 目录 | Agent 技能沉淀、策展和使用记录 |
| `skills/.agent/.curator` | 目录 | Agent 技能策展说明 |
| `skills/.agent/.templates` | 目录 | Agent 生成技能所用的文档和清单模板 |
| `skills/.agent/.usage.json` | 文件 | Agent 技能调用统计 |
| `skills/.agent/xbot-self-evolution` | 目录 | Xbot Agent 技能维护与复盘指引 |
| `skills/code_assistant` | 目录 | 代码协作技能的说明与注册配置 |
| `skills/code_assistant/SKILL.md` | 文件 | 代码协作技能的使用约定与工作流程 |
| `skills/code_assistant/skill.toml` | 文件 | 代码协作技能的注册元数据 |
| `skills/微信发送skill` | 目录 | 通过微信 869 发送媒体与附件的技能 |
| `skills/微信发送skill/SKILL.md` | 文件 | 微信媒体发送参数与操作示例 |
| `skills/微信发送skill/_meta.json` | 文件 | 微信媒体发送技能的来源与发布元数据 |
| `skills/微信发送skill/send_869_media.py` | 文件 | 调用微信 869 通道发送媒体和附件 |
| `skills/微信发送skill/send_voice_auto.py` | 文件 | 准备并通过微信 869 发送语音 |
| `skills/微信发送skill/skill.toml` | 文件 | 微信媒体发送技能的注册元数据 |
| `specs` | 目录 | SDD 文档根目录：每个 feature 一个子目录 |
| `specs/001-agent-workspace` | 目录 | 移除微伴社区与 Agent 工作台重构的 SDD 记录 |
| `specs/001-agent-workspace/plan.md` | 文件 | 实施顺序、Hermes 升级兼容约束及回滚方案 |
| `specs/001-agent-workspace/spec.md` | 文件 | 本次改造范围和网页对话验收标准 |
| `specs/001-agent-workspace/tasks.md` | 文件 | 任务进度、验证结果、风险与剩余阻塞 |
| `specs/002-hermes-upgrade` | 目录 | 内嵌 Hermes 版本升级的需求、方案和验收记录 |
| `specs/002-hermes-upgrade/plan.md` | 文件 | 固定发行版、运行时适配和回退方案 |
| `specs/002-hermes-upgrade/spec.md` | 文件 | Hermes 版本升级范围与验收要求 |
| `specs/002-hermes-upgrade/tasks.md` | 文件 | 升级状态、验证结果和发布前事项 |
| `specs/003-audit-remediation` | 目录 | 依赖告警、SDK 兼容与目录复核的 SDD 记录 |
| `specs/003-audit-remediation/plan.md` | 文件 | 依赖升级、兼容验证与回退方案 |
| `specs/003-audit-remediation/spec.md` | 文件 | 告警修复的范围与验收标准 |
| `specs/003-audit-remediation/tasks.md` | 文件 | 执行进度、审计证据和发布剩余事项 |
| `specs/005-wechat-workbench` | 目录 | 869 私聊头像同步及机器人出站回显规范 |
| `specs/005-wechat-workbench/plan.md` | 文件 | 数据来源、结果提示、投递后持久化及回滚方案 |
| `specs/005-wechat-workbench/spec.md` | 文件 | 私聊头像、出站历史和同步结果的验收标准 |
| `specs/005-wechat-workbench/tasks.md` | 文件 | 实现进度、本地回归与线上待验收项 |
| `specs/006-wechat-channel-label` | 目录 | 微信客户端通道的界面命名与兼容验收 |
| `specs/006-wechat-channel-label/plan.md` | 文件 | 展示层改名、内部标识保留与测试方案 |
| `specs/006-wechat-channel-label/spec.md` | 文件 | 改名范围、非目标与验收标准 |
| `specs/006-wechat-channel-label/tasks.md` | 文件 | 浏览器回归和落盘状态 |
| `specs/007-xbot-pro-release` | 目录 | 独立生产更新与公开框架发布记录 |
| `specs/007-xbot-pro-release/plan.md` | 文件 | 产物验证、公开审核与应用回滚方案 |
| `specs/007-xbot-pro-release/spec.md` | 文件 | 生产更新、仓库发布及截图验收范围 |
| `specs/007-xbot-pro-release/tasks.md` | 文件 | 生产验收、PR 检查及审批状态 |
| `specs/ACTIVE` | 文件 | 当前进行中的 feature-id（pg new/use 维护） |
| `specs/_template` | 目录 | SDD 模板（spec/plan/tasks） |
| `specs/_template/plan.md` | 文件 | 技术方案模板 |
| `specs/_template/spec.md` | 文件 | 需求规格模板 |
| `specs/_template/tasks.md` | 文件 | 任务清单模板 |
| `src` | 目录 | Python 的 src-layout 源码根目录 |
| `src/xbot` | 目录 | Xbot 后端应用包 |
| `src/xbot/__init__.py` | 文件 | 声明 Xbot 包和版本元数据 |
| `src/xbot/adapters` | 目录 | 微信、QQ、Telegram 等通道协议接入 |
| `src/xbot/agent` | 目录 | 模型执行、会话、调度和 Agent 工具 |
| `src/xbot/agent/hermes_runtime.py` | 文件 | 适配内嵌 Hermes 的模型、会话、工具权限与状态 |
| `src/xbot/agent/mcp.py` | 文件 | 连接 MCP HTTP 和 stdio 传输，管理会话和注册工具 |
| `src/xbot/agent/runtime.py` | 文件 | 编排执行、发布流事件并记录任务结果 |
| `src/xbot/api` | 目录 | HTTP 接口、依赖注入与鉴权 |
| `src/xbot/api/v1/agent.py` | 文件 | Agent 工具、任务、事件、网页对话流和历史接口 |
| `src/xbot/api/v1/router.py` | 文件 | 注册控制台和通道 API 模块 |
| `src/xbot/app` | 目录 | FastAPI 应用工厂、生命周期与静态资源挂载 |
| `src/xbot/cli` | 目录 | 命令行入口和运维命令 |
| `src/xbot/conversations` | 目录 | 会话解析、历史读取与上下文管理 |
| `src/xbot/core` | 目录 | 配置、日志、异常、事件与代理基础能力 |
| `src/xbot/knowledge` | 目录 | 群聊知识库、附件提取和 Wiki 编译 |
| `src/xbot/messaging` | 目录 | 通用消息模型、队列、消费与投递 |
| `src/xbot/plugins` | 目录 | 插件发现、隔离、注册和执行 |
| `src/xbot/runtime` | 目录 | 应用依赖组装、消息路由和运行生命周期 |
| `src/xbot/schemas` | 目录 | 接口和内部服务共用的数据结构 |
| `src/xbot/services` | 目录 | 系统配置、通道与运行状态的应用服务 |
| `src/xbot/skills` | 目录 | 技能发现、注册、管理和运行 |
| `src/xbot/storage` | 目录 | ORM 模型、数据库连接和查询仓储 |
| `src/xbot/storage/models.py` | 文件 | 定义数据库模型、约束和索引 |
| `src/xbot/storage/repositories/agent_repo.py` | 文件 | Agent 任务、历史、事件和产物的持久化查询 |
| `tests` | 目录 | Xbot 自动化回归测试 |
| `tests/conftest.py` | 文件 | 设置测试路径并隔离插件、技能和环境配置 |
| `tests/fixtures` | 目录 | 隔离测试所用的样板插件和技能 |
| `tests/fixtures/plugins` | 目录 | 用于验证插件加载和运行的合成插件 |
| `tests/fixtures/skills` | 目录 | 用于验证技能加载和运行的合成技能 |
| `tests/integration` | 目录 | 真实组件协作的集成回归 |
| `tests/integration/api` | 目录 | API 鉴权、应用接线与 Agent 对话集成回归 |
| `tests/integration/api/test_agent_workspace.py` | 文件 | 网页 Agent 对话鉴权、历史、流式事件、并发和断线回归 |
| `tests/integration/api/test_hermes_smoke.py` | 文件 | 用本地模型桩回归真实 Hermes 的流式输出、会话和人设隔离 |
| `tests/integration/api/test_wechat_workbench.py` | 文件 | 工具台私聊头像、通道隔离、出站回执和实时事件回归 |
| `tests/integration/messaging` | 目录 | 消息队列与 Redis Streams 行为回归 |
| `tests/unit` | 目录 | 独立模块的单元回归 |
| `tests/unit/core` | 目录 | 运行核心、Agent、插件、通道和存储行为回归 |
| `tests/unit/core/test_agent_chat_concurrency.py` | 文件 | 通道 Agent 排队、群人设和会话串行回归 |
| `tests/unit/core/test_hermes_agent_runtime.py` | 文件 | Hermes 构造、模型路由、权限、会话清理与通道回归 |
| `tests/unit/core/test_hermes_context_policy.py` | 文件 | 上下文窗口、压缩策略及分群模型回归 |
| `tests/unit/core/test_hermes_session_resolution.py` | 文件 | 验证 Hermes 压缩后的单级及多级会话续接 |
| `tests/unit/core/test_migrations.py` | 文件 | 空库升级、回退、重建与 ORM 一致性检查 |
| `ui` | 目录 | React 控制台与 TypeScript、Vite 构建配置 |
| `ui/index.html` | 文件 | Vite 构建和挂载控制台的 HTML 入口 |
| `ui/package-lock.json` | 文件 | 锁定 React 控制台及其构建链的依赖版本和完整性 |
| `ui/package.json` | 文件 | 控制台直接依赖及开发、类型检查和构建命令 |
| `ui/public` | 目录 | Vite 构建时复制的静态资源 |
| `ui/public/assets` | 目录 | 导航与各工作区共用的插画等资源 |
| `ui/src` | 目录 | 控制台 API、类型、样式和 React 源码 |
| `ui/src/api.ts` | 文件 | 控制台请求、Token 处理与 Agent 流解析 |
| `ui/src/main.tsx` | 文件 | 挂载 React 应用和加载共享样式 |
| `ui/src/styles-centers.css` | 文件 | 控制台各功能中心的样式 |
| `ui/src/styles-content.css` | 文件 | 共享内容和文本样式 |
| `ui/src/styles-extra.css` | 文件 | 控制台补充组件样式 |
| `ui/src/styles-hardening.css` | 文件 | 控制台布局约束和兼容样式 |
| `ui/src/styles-motion.css` | 文件 | 界面过渡和动效 |
| `ui/src/styles-responsive.css` | 文件 | 控制台全局窄屏适配 |
| `ui/src/styles.css` | 文件 | 主题令牌和应用外壳的基础样式 |
| `ui/src/types.ts` | 文件 | 控制台 API 数据和共享类型 |
| `ui/src/ui` | 目录 | 控制台页面、业务面板和共享组件 |
| `ui/src/ui/AgentWorkspace.tsx` | 文件 | 会话侧栏、流式消息、输入框和执行详情组件 |
| `ui/src/ui/App.tsx` | 文件 | 控制台导航、公共数据与页面入口，Agent 页面直接进入工作台 |
| `ui/src/ui/ConfigCenter.tsx` | 文件 | 系统与通道的配置中心，可打开指定分区 |
| `ui/src/ui/HomeDashboard.tsx` | 文件 | 控制台首页、快捷入口与运行总览 |
| `ui/src/ui/IllustrationHero.tsx` | 文件 | 非对话页面复用的插画标题区 |
| `ui/src/ui/MarkdownContent.tsx` | 文件 | 控制台消息 Markdown 渲染 |
| `ui/src/ui/OperationsCenter.tsx` | 文件 | 后台任务、定时计划与运行事件管理 |
| `ui/src/ui/WechatPersonaPanel.tsx` | 文件 | 微信会话 Agent 人设编辑面板 |
| `ui/src/ui/agent-workspace.css` | 文件 | 紧凑工作区、消息滚动与窄屏会话列表 |
| `ui/src/ui/wechatChannelLabel.ts` | 文件 | 微信客户端通道统一展示名与旧提示转换 |
| `ui/src/vite-env.d.ts` | 文件 | Vite 环境和导入的 TypeScript 类型声明 |
| `ui/tsconfig.json` | 文件 | 控制台 TypeScript 编译和类型检查约束 |
| `ui/vite.config.ts` | 文件 | Vite 插件和应用构建配置 |
| `uv.lock` | 文件 | 锁定 Python 运行和开发依赖及 Hermes 源码位置 |
| `vendor` | 目录 | 保留历史第三方记录；新版构建不读取本目录 |
| `vendor/hermes` | 目录 | 旧版 Hermes 源码快照，非当前构建输入 |
| `vendor/hermes-upstream.json` | 文件 | 用于校验和重建旧版 Hermes 快照的提交与归档清单 |
<!-- pg:dir:end -->
