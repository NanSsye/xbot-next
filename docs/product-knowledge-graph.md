# 产品知识图谱（可读视图）

> 自动生成，图谱版本 `94df383+011-release-center@20261127143544`。**请勿手改**；修改请用 `pg update`。
> 数据源：`knowledge/graph/nodes.jsonl`（37 节点）、`edges.jsonl`（42 边）。

## 共享 / 业务（shared）

### config

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `config.clean-compose` | 独立实例 Compose | active | docker-compose.yml | 完整应用根目录；新安装数据库绑定 database/postgres 和 database/redis，Xbot 进程不访问数据库物理文件 |

### spec

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `spec.001-agent-workspace` | 移除微伴社区并重构 Agent 工作台 | active | specs/001-agent-workspace/spec.md | 需求 001-agent-workspace：移除微伴社区并重构 Agent 工作台 |
| `spec.002-hermes-upgrade` | 升级内嵌 Hermes 至 v0.23.4 | active | specs/002-hermes-upgrade/spec.md | 需求 002-hermes-upgrade：升级内嵌 Hermes 至 v0.23.4 |
| `spec.003-audit-remediation` | 复核并修复 Hermes 升级后告警 | active | specs/003-audit-remediation/spec.md | 复核并处理升级后的依赖告警；记录 Hermes 实际发行版与剩余上游风险。 |
| `spec.005-wechat-workbench` | 微信工作台 869 头像与机器人回复回显 | active | specs/005-wechat-workbench/spec.md | 需求 005-wechat-workbench：微信工作台 869 头像与机器人回复回显 |
| `spec.006-wechat-channel-label` | 统一微信客户端通道展示名称 | active | specs/006-wechat-channel-label/spec.md | 需求 006-wechat-channel-label：统一微信客户端通道展示名称 |
| `spec.007-xbot-pro-release` | 发布新版框架与 README | active | specs/007-xbot-pro-release/spec.md | 审核并提交公开发布快照，不包含实例专用运维配置。 |
| `spec.008-syndex-console-design` | 按 SYNDEX 工作台重整 Xbot 控制台 | active | specs/008-syndex-console-design/spec.md | 需求 008-syndex-console-design：按 SYNDEX 工作台重整 Xbot 控制台 |
| `spec.009-channel-config-cards` | 接入通道卡片配置 | active | specs/009-channel-config-cards/spec.md | 需求 009-channel-config-cards：接入通道卡片配置 |
| `spec.010-console-settings-ux` | 控制台设置：从首次接入到日常管理 | active | specs/010-console-settings-ux/spec.md | 控制台设置改版已本地实现并通过模拟浏览器回归及配置接口测试，未部署。 |
| `spec.011-release-center` | 独立发布后台与整版更新 | active | specs/011-release-center/spec.md | 需求 011-release-center：独立发布后台与整版更新 |

### doc

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `doc.github-readme` | GitHub 首页与快速开始 | active | README.md | 以演示数据展示新版桌面总览、Agent 对话、微信工作台、接入通道和模型配置，区分 Docker 新实例、本地安装和开发。 |

## 前端（frontend）

### page

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `page.agent-workspace` | Agent 对话工作台 | active | ui/src/ui/AgentWorkspace.tsx | 中性工作台主题，192px 独立历史栏、紧凑标题及居中消息流；保留独立会话、流式消息、历史与执行过程。 |
| `page.channel-management` | 接入通道和通道配置 | active | ui/src/ui/App.tsx | 四种外部通道从卡片打开右侧独立配置抽屉，手机全宽；卡片开关管理启停，运行状态不代表登录。Web 无配置表单。 |
| `page.framework-update` | 框架更新确认 | active | ui/src/ui/FrameworkUpdate.tsx | 控制台偏好展示前端版本及官方增量下载；本机安装单独预检，其他页面保留右下角入口 |
| `page.official-marketplace` | 官方市场 | active | ui/src/ui/OfficialMarketplace.tsx | 独立目录页，按插件或技能浏览和下载；本机扩展页不请求官方服务。 |
| `page.wechat-workbench` | 微信工作台 | active | ui/src/ui/App.tsx | 会话和消息读取头像；失败回退首字。同步提示按私聊头像返回量显示，出站消息沿用右侧气泡和实时事件。 |

### component

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `component.agent-model-settings` | Agent 模型设置 | active | ui/src/ui/ConfigCenter.tsx | 设置首页提供三组任务、中文搜索与右侧抽屉；按字段隔离保存，支持模型列表重试、手动模型和试聊入口。 |
| `component.console-shell` | 控制台工作区外壳 | active | ui/src/styles-hardening.css | 按 SYNDEX 对话页建立中性明暗主题、紧凑导航和轻边框；复用通用页头。 浏览器标签复用 Xbot 吉祥物。 |
| `component.wechat-client-label` | 微信客户端通道显示名 | active | ui/src/ui/wechatChannelLabel.ts | 首页、通道、配置和事件展示统一为微信客户端通道，保留原 API 路径、配置键和内容数据。 |

### config

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `config.ui-dependency-lock` | 控制台依赖锁定 | active | ui/package-lock.json | 锁定控制台和构建依赖；Vite 保持 6.x，定向升级受审计影响的包，不改变页面与构建入口。 |

## 后端（backend）

### api

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `api.agent-web-chat` | 网页 Agent 会话接口 | active | src/xbot/api/v1/agent.py | NDJSON 对话流与分页历史，鉴权由部署配置决定；通过任务 ID 隔离事件并限制同会话并发。 |
| `api.framework-update` | 宿主机更新任务 | active | src/xbot/api/v1/framework.py | 提交确认编号，持久查询任务结果 |
| `api.release-readiness` | 发行就绪检查 | active | src/xbot/api/v1/system.py | 检查启动时发行摘要、引擎、数据库和队列 |
| `api.wechat-workbench` | 微信工作台 API | active | src/xbot/api/v1/wechat.py | 同步 869 私聊联系人头像并返回 private_avatars_received；历史头像按适配器隔离；工作台发送共用出站记录。 |

### service

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `service.release-switch` | 宿主机整版切换 | active | scripts/release_switch.py | 受控暂存目录切换和旧版本复验，尚未连接网页 |
| `service.wechat-workbench-outgoing` | 微信工作台出站消息入库 | active | src/xbot/runtime/engine.py | 同步和队列成功发送的 869 文本共用历史写入和 message.created 事件；不会把模型输出或发送失败投影成已发送。 |

### data_model

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `data_model.agent-web-history` | Agent 网页对话历史 | active | src/xbot/storage/repositories/agent_repo.py | 复用任务记录中的来源、输入、输出与状态。网页对话不新增表，不持久化增量事件。 |
| `data_model.clean-schema` | 独立实例空库基线 | active | migrations/versions/fresh_0001_initial_clean_schema.py | 冻结新实例的初始 Alembic 结构；不包含社区表或历史升级链，只用于新库。 |

### integration

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `integration.hermes-xbot` | Xbot 内嵌 Hermes | active | src/xbot/agent/hermes_runtime.py | 内嵌固定的 Hermes v0.23.4。通过上游持久化接口续接压缩会话，并保留流式回调、群聊模型、人设和 Xbot 工具权限。 |
| `integration.instance-heartbeat` | 实例心跳 | active | src/xbot/app/lifespan.py | 未接入不发送；生产已完成连续心跳验证 |
| `integration.official-catalog` | 客户端官方目录 | active | src/xbot/api/v1/skills.py | 读取独立发布中心目录 |
| `integration.wechat869-workbench` | 869 联系人资料与发送回执 | active | src/xbot/adapters/wechat869/client.py | 复用已登录客户端获取指定联系人的头像；文本发送仅在收到有效回执时确认成功。 |
| `integration.xbot-mcp` | Xbot MCP 工具连接 | active | src/xbot/agent/mcp.py | 用 MCP SDK v2 连接 HTTP 和 stdio 服务，在同一后台任务中打开和关闭每条连接，支持跨任务重载。 |

### config

| ID | 名称 | 状态 | 路径 | 说明 |
|----|------|------|------|------|
| `config.hermes-release` | Hermes 固定发行版 | active | configs/hermes-release.json | 固定官方稳定版标签、提交和归档 SHA-256；本地与 Docker 共用准备脚本和 uv.lock。 |
| `config.public-channel-defaults` | 公开通道默认配置 | active | configs/xbot.toml | 微信客户端通道默认关闭且使用回环地址，实际通道由部署者显式配置。 |
| `config.python-dependency-lock` | Python 依赖锁定 | active | uv.lock | 锁定现有 Python 运行和开发依赖；PDF 提取使用 pypdf 6，Agent 环境沿用 Hermes 发行版的 MCP SDK v2 约束。 |

## 关系

| 起点 | 关系 | 终点 |
|------|------|------|
| 网页 Agent 会话接口 (`api.agent-web-chat`) | depends_on | Agent 网页对话历史 (`data_model.agent-web-history`) |
| 网页 Agent 会话接口 (`api.agent-web-chat`) | depends_on | Xbot 内嵌 Hermes (`integration.hermes-xbot`) |
| 宿主机更新任务 (`api.framework-update`) | depends_on | 宿主机整版切换 (`service.release-switch`) |
| 微信工作台 API (`api.wechat-workbench`) | depends_on | 869 联系人资料与发送回执 (`integration.wechat869-workbench`) |
| 微信工作台 API (`api.wechat-workbench`) | depends_on | 微信工作台出站消息入库 (`service.wechat-workbench-outgoing`) |
| Agent 模型设置 (`component.agent-model-settings`) | implements | 按 SYNDEX 工作台重整 Xbot 控制台 (`spec.008-syndex-console-design`) |
| 控制台工作区外壳 (`component.console-shell`) | implements | 按 SYNDEX 工作台重整 Xbot 控制台 (`spec.008-syndex-console-design`) |
| 微信客户端通道显示名 (`component.wechat-client-label`) | implements | 统一微信客户端通道展示名称 (`spec.006-wechat-channel-label`) |
| 独立实例 Compose (`config.clean-compose`) | depends_on | Hermes 固定发行版 (`config.hermes-release`) |
| 独立实例 Compose (`config.clean-compose`) | depends_on | 独立实例空库基线 (`data_model.clean-schema`) |
| 公开通道默认配置 (`config.public-channel-defaults`) | affects | 869 联系人资料与发送回执 (`integration.wechat869-workbench`) |
| Python 依赖锁定 (`config.python-dependency-lock`) | implements | 复核并修复 Hermes 升级后告警 (`spec.003-audit-remediation`) |
| 控制台依赖锁定 (`config.ui-dependency-lock`) | implements | 复核并修复 Hermes 升级后告警 (`spec.003-audit-remediation`) |
| Agent 网页对话历史 (`data_model.agent-web-history`) | depends_on | 独立实例空库基线 (`data_model.clean-schema`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | implements | 发布新版框架与 README (`spec.007-xbot-pro-release`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | related_to | Agent 模型设置 (`component.agent-model-settings`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | related_to | 独立实例 Compose (`config.clean-compose`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | related_to | 公开通道默认配置 (`config.public-channel-defaults`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | related_to | Agent 对话工作台 (`page.agent-workspace`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | related_to | 接入通道和通道配置 (`page.channel-management`) |
| GitHub 首页与快速开始 (`doc.github-readme`) | related_to | 微信工作台 (`page.wechat-workbench`) |
| Xbot 内嵌 Hermes (`integration.hermes-xbot`) | depends_on | Hermes 固定发行版 (`config.hermes-release`) |
| Xbot 内嵌 Hermes (`integration.hermes-xbot`) | depends_on | Python 依赖锁定 (`config.python-dependency-lock`) |
| Xbot 内嵌 Hermes (`integration.hermes-xbot`) | implements | 升级内嵌 Hermes 至 v0.23.4 (`spec.002-hermes-upgrade`) |
| 实例心跳 (`integration.instance-heartbeat`) | implements | 独立发布后台与整版更新 (`spec.011-release-center`) |
| Xbot MCP 工具连接 (`integration.xbot-mcp`) | depends_on | Python 依赖锁定 (`config.python-dependency-lock`) |
| Agent 对话工作台 (`page.agent-workspace`) | calls | 网页 Agent 会话接口 (`api.agent-web-chat`) |
| Agent 对话工作台 (`page.agent-workspace`) | depends_on | 控制台工作区外壳 (`component.console-shell`) |
| Agent 对话工作台 (`page.agent-workspace`) | depends_on | 控制台依赖锁定 (`config.ui-dependency-lock`) |
| Agent 对话工作台 (`page.agent-workspace`) | implements | 移除微伴社区并重构 Agent 工作台 (`spec.001-agent-workspace`) |
| Agent 对话工作台 (`page.agent-workspace`) | related_to | Agent 模型设置 (`component.agent-model-settings`) |
| 接入通道和通道配置 (`page.channel-management`) | depends_on | 控制台工作区外壳 (`component.console-shell`) |
| 接入通道和通道配置 (`page.channel-management`) | depends_on | 微信客户端通道显示名 (`component.wechat-client-label`) |
| 接入通道和通道配置 (`page.channel-management`) | implements | 接入通道卡片配置 (`spec.009-channel-config-cards`) |
| 框架更新确认 (`page.framework-update`) | calls | 宿主机更新任务 (`api.framework-update`) |
| 官方市场 (`page.official-marketplace`) | calls | 客户端官方目录 (`integration.official-catalog`) |
| 微信工作台 (`page.wechat-workbench`) | depends_on | 微信工作台 API (`api.wechat-workbench`) |
| 微信工作台 (`page.wechat-workbench`) | depends_on | 控制台工作区外壳 (`component.console-shell`) |
| 微信工作台 (`page.wechat-workbench`) | implements | 微信工作台 869 头像与机器人回复回显 (`spec.005-wechat-workbench`) |
| 宿主机整版切换 (`service.release-switch`) | depends_on | 发行就绪检查 (`api.release-readiness`) |
| 微信工作台出站消息入库 (`service.wechat-workbench-outgoing`) | depends_on | 869 联系人资料与发送回执 (`integration.wechat869-workbench`) |
| 控制台设置：从首次接入到日常管理 (`spec.010-console-settings-ux`) | related_to | Agent 模型设置 (`component.agent-model-settings`) |
