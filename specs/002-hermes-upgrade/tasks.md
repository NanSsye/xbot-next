# 002-hermes-upgrade 任务清单（tasks）：升级内嵌 Hermes 至 v0.23.4

> 关联：[spec.md](./spec.md) · [plan.md](./plan.md) | 最后更新：2026-11-26
> 格式：`- [ ] T001 描述 | 依赖: - | 负责人: Agent`；`[ ]` 未开始，`[~]` 进行中，`[x]` 完成，`[!]` 阻塞。

## 任务
- [x] T001 核实官方稳定版提交和归档哈希 | 依赖: - | 负责人: Agent
- [x] T002 准备固定源码与运行依赖，统一本地与容器安装配置 | 依赖: T001 | 负责人: Agent
- [x] T003 适配会话、工具权限和模型，完成本地回归 | 依赖: T002 | 负责人: Agent
- [x] T004 同步知识图谱（前端+后端）、目录说明、changelog，pg check 通过 | 依赖: T003 | 负责人: Agent

## 下一步
- 后续发布前，在独立 Docker 实例验收真实模型、通道和 Redis；复核并处理依赖审计告警。Windows 安装脚本未实机运行。

## 阻塞项
- 本地升级不受阻。发布验证尚未完成：本机没有 Docker CLI，未构建或运行镜像；未使用线上数据、模型或通道凭据。

## 进展记录
- 2026-11-26 确认官方稳定版 v0.23.4、提交及归档哈希，按 Python 3.14 和 uv.lock 安装。未修改 vendor 或线上。
- `pytest -q --tb=short -rs`：308 通过，2 个 Redis 集成用例因缺服务跳过。使用真实 Hermes 和本地 HTTP 模型桩验证流式、会话与人设隔离、401 脱敏；另验证压缩续接、角色权限、工具参数改写及临时旧版 SQLite 样本续接。
- `uv lock --check`、`uv sync --locked --extra agent --extra dev --check`、改动范围的 `ruff check`、`bash -n`、`npm run build` 通过。Linux/amd64、Windows 锁定依赖试算通过，不能代替实机安装。
- `uv audit --locked` 未通过：152 个包，199 条报告（119 个不同的报告 ID，包含上游占位版本 `0.0.0` 的 Hermes；不能当作已证实适用于发行提交）。发布前逐项复核上游固定依赖及 Xbot 依赖，不以本次功能回归作为生产验收。
- `pg check`：0 ERROR、195 WARN。剩余警告均为本次未改动路径的存量目录职责 TODO。

## 改动索引

- `configs/hermes-release.json`、`scripts/prepare_hermes.py`：固定发行提交和哈希，复用安全解压，不改第三方目录；`.gitignore`、`.dockerignore`、`.pgignore` 排除生成的 Hermes 源码目录。
- `pyproject.toml`、`uv.lock`：统一 Python 3.14、Hermes 依赖和 SQLAlchemy 异步运行依赖。`Dockerfile`、`scripts/install.sh`、`scripts/install.ps1`、`scripts/upgrade.sh`、`scripts/upgrade.ps1`：使用固定归档与锁文件安装。
- `src/xbot/agent/hermes_runtime.py`：新版持久化、模型窗口、人设、工具权限和辅助路由。前端和公开 API 不变。
- `tests/integration/api/test_hermes_smoke.py`、`tests/integration/api/test_app.py`、`tests/unit/core/test_hermes_agent_runtime.py`、`tests/unit/core/test_hermes_context_policy.py`、`tests/unit/core/test_hermes_session_resolution.py`：对话冒烟、OpenAPI 契约和运行时适配回归。
- `README.md`、`docs/hermes-agent-integration.md`、`docs/docker-deployment.md`：安装、持久化及回退说明；知识图谱、目录说明及 changelog 同步。
