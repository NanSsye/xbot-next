# 任务

## 服务器基线（本轮）

- [x] 只读提取白名单源码；部署前端原样构建验证 15 个资源 SHA-256；容器确认 Hermes 0.20.0。
- [x] 对照服务器接口、持久层和 UI，移植对话能力。保留共享视觉与非 Agent 路由。
- [x] 移除微伴社区专属入口、插件、技能、路由和工具注册。
- [x] 移除 Agent 对话页顶部大横幅，验证桌面和手机首屏输入框与历史列表。
- [x] 建立独立发布配置、空库迁移，删除已证实不再加载的归档代码。
- [x] 在本地验证 API、浏览器、前端构建与空库迁移，并同步前后端图谱和目录说明。
- [ ] 发布前在独立 Docker 环境使用真实模型和通道验收；先处理前端依赖审计与静态媒体访问问题。
- [x] Hermes 升级交由 `002-hermes-upgrade`；本轮旧版验证记录保留，不改 vendor 或线上。

## 当前副本验证

- `npm --prefix ui run build`（TypeScript + Vite）通过；改动范围 `ruff check` 通过。专项 `pytest -q --tb=short`：Agent、配置、知识库、微信人设和迁移共 47 项通过，QQ 隔离运行 9 项通过。群人设测试修正旧断言为服务器基线已使用的 `persona_prompt`，未调整运行逻辑。
- 本地浏览器（1440×900、390×844）实测进入 Agent 页无大横幅，对话区距主内容顶部 12px，输入框首屏可见；桌面显示会话侧栏、手机可按需打开。复验流式中文、相同文本两轮、IME、恢复、失败、旧对话和产物。使用临时 SQLite 与模拟模型，不接线上。
- 以已保存的原构建离线对照：九个非 Agent 页面标题、插画路径、横幅宽度和标题颜色一致。删除的任务、记忆聚合请求仅服务原横幅，保留现有后端 API 和独立执行详情。
- 空 SQLite 和临时 PostgreSQL 17 的初始迁移升级、降级、再升级及 `alembic check` 通过；PostgreSQL 共 27 张表（含版本表），无微伴社区表。
- 当时使用 Hermes 0.20.0；用本地模型桩重验流式回调、会话续接、会话隔离和失败状态。当前版本见 `002-hermes-upgrade`。
- 未构建或运行 Docker 镜像，本机无 Docker CLI；无全量回归或真实通道验收。`npm audit --omit=dev` 报 5 项高危、1 项中危，依赖未改。静态媒体仍沿用旧版访问行为，新实例不直接公开。原插件配置有疑似明文凭据，新副本已置空；需人工确认并轮换，不在本轮处理线上配置。
- `pg check` 要求 0 ERROR；未修改模块的存量目录职责 TODO 允许保留为 WARN。

## 旧 GitHub 原型记录（不作为服务器版验收）

- [x] 克隆基线、查实现与 SYNDEX 设计，确认现有 Hermes 及上游版本。
- [x] 清理微伴社区可执行功能，保留历史迁移；回归确认社区 API 不再暴露。
- [x] 改造 Agent 工作台和会话 API；验证断线、并发、产物与桌面和手机布局。
- [x] 验证当前 Hermes 0.20.0 的流式回调、SQLite 多轮续接和 Web 会话隔离。
- [x] 在隔离环境安装并探测 Hermes v0.23.4 的接口边界，复现联合依赖冲突。
- [!] 集成新版 Hermes：需确认受控更新 vendor 镜像与运行依赖的范围；未切换版本。
- [ ] 在独立环境上用真实模型和相同容器配置验收新版；不在生产环境测试。

## 旧 GitHub 原型验证记录

- `npm run build`（TypeScript + Vite）通过；当前依赖锁未更改。`npm audit --omit=dev --json` 报 5 项高危、1 项中危；此轮未升级前端依赖，发布前需处理。
- `PYTHONPATH=vendor/hermes uv run --no-sync pytest -q --tb=short` 对 Agent、群知识库、配置、产物、迁移和 vendor 同步专项：58 项通过；`PYTHONPATH=. uv run --no-sync python -m pytest -q --tb=short tests/unit/core/test_qq_adapter.py`：31 项通过。QQ 测试单独运行，以免上游 `plugins` 包遮蔽 Xbot 本地插件。受影响 Python 文件 `ruff check` 与 `git diff --check HEAD` 均通过。
- Chrome 和 390px 移动视口：真实网页接口、临时 SQLite、模拟模型。已验中文 IME、流式中文和未闭合代码围栏、两轮同文本、刷新恢复、执行过程与产物、旧对话只读、模型失败历史。
- Hermes 0.20.0：通过本地 HTTP 模型桩直接调用嵌入适配层，验证流式增量、同会话续接、会话隔离，以及模型 401 不被记录成成功或暴露原错误正文。
- Python 验证仅在本地虚拟环境补装 Xbot 锁中已有的 `greenlet==3.5.5`；未改项目依赖。无真实模型、生产 PostgreSQL 或 Docker 镜像端到端验收。

## 改动索引

- `ui/src/ui/AgentWorkspace.tsx`、`agent-workspace.css`：网页对话组件和响应式布局；`App.tsx`、`ConfigCenter.tsx`：入口、消息渲染和模型设置跳转；`ui/src/api.ts`、`types.ts`：流与历史接口；`styles.css`：删除社区专用样式。
- `src/xbot/api/v1/agent.py`：会话接口；`agent/runtime.py`、`agent/hermes_runtime.py`（位于 `src/xbot`）：任务标识、推送和失败状态；`storage/repositories/agent_repo.py`：历史筛选分页；`api/v1/router.py`、`storage/models.py`：移除社区注册。
- 移除 `src/xbot/community/`、`src/xbot/api/v1/community.py`、`plugins/WeibanCommunity/`、`skills/weiban-admin/`、`skills/weiban-knowledge/`、`src/xbot/agent/tools/hermes_weiban*.py`、`ui/src/ui/CommunityCenter.tsx` 以及社区专属测试；通道 Agent 插件与测试夹具去掉社区专属提示。
- `tests/integration/api/test_agent_workspace.py`：新增 API 回归；`tests/unit/core/test_hermes_agent_runtime.py`、`test_qq_adapter.py`：更新角色工具断言和通用测试文案。文档、图谱和目录说明由 SDD 工具同步。
