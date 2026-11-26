# 003-audit-remediation 任务清单（tasks）：复核并修复 Hermes 升级后告警

> 关联：[spec.md](./spec.md) · [plan.md](./plan.md) | 最后更新：2026-11-26
> 格式：`- [ ] T001 描述 | 依赖: - | 负责人: Agent`；`[ ]` 未开始，`[~]` 进行中，`[x]` 完成，`[!]` 阻塞。

## 任务
- [x] T001 扫描并记录基线，落盘需求 | 依赖: - | 负责人: Agent
- [x] T002 落盘实施计划和回退范围 | 依赖: T001 | 负责人: Agent
- [x] T003 定向修复依赖、核实 Hermes 公告并完成回归 | 依赖: T002 | 负责人: Agent
- [x] T004 同步知识图谱（前端+后端）、目录说明、changelog，pg check 通过 | 依赖: T003 | 负责人: Agent

## 下一步
- 发布前在独立镜像复验，保持 Hermes 飞书网关关闭，待上游确认 CVE-2026-10224 的修复后再考虑启用。

## 阻塞项
- 本机没有 Docker CLI，未做镜像构建或真实通道验收；不连接或改动现有线上容器。

## 进展记录
- 2026-11-26：`uv audit --locked --output-format json` 扫描 152 包：199 → 20 条，119 → 10 个去重报告 ID；其余 Python 包 179 → 0 条，未设忽略。仍因 `hermes-agent==0.0.0` 源码占位而返回 1。
- `npm audit` 和 `npm audit --omit=dev` 均返回 0 条（此前 5 高、1 中）。`npm ci --ignore-scripts`、`npm run build`（含 `tsc -b`）通过。
- `uv lock --check`、`uv sync --locked --extra agent --extra dev --check`、限定改动范围的 `ruff check` 和 `git diff --check` 通过。全工作树 `git diff --check` 仍报前序修改的格式问题，本轮未整理无关文件。
- `uv run --locked --extra agent --extra dev pytest -q --tb=short -rs`：310 通过、2 个默认 Redis 用例跳过；再用无 TCP 监听的临时本地 Redis 单独运行队列测试文件：3 通过，覆盖两项原本跳过的用例。默认套件仍有 313 条弃用警告，主要为旧的 UTC 时间调用及 Hermes `SessionDB` 测试接口，不计为审计告警。
- 新增合成 PDF 提取/保留原件与真实 MCP SDK 的 HTTP 请求头、stdio、跨任务重载和关闭回归；Telegram MCP 插件入口可导入，未调用发送工具。
- `pg dir` 待填职责 0 项；`pg check`：0 ERROR、195 WARN → 0 ERROR、0 WARN。
- 复用项目的锁文件、Agent MCP 管理器、PDF 提取器和构建流程。四个非测试、非 SDD 的实现文件是 Python 清单、两端锁文件与 MCP 适配；额外文件是为避免依赖升级导致通道回归，不拆成无法独立验收的变更。

## Hermes 公告核对

实际构建使用官方 `v0.23.4`（`8fc0374447313e276f6b9a2764bfc750190c966a`）。对照 GitHub Advisory Database，并用上游 GitHub Compare API 验证公告关联修复提交是该版本的祖先。`CVE-2026-10221` 的公告未标修复版，但其关联 PR #69860 已合并，且合并提交在当前发行版内。

| 公告 | 核对证据 |
|---|---|
| CVE-2026-9353 | 修复 `7ebebfbb8d10` 已包含 |
| CVE-2026-53869 | 修复 `d9ec90585cf7` 已包含 |
| CVE-2026-53870 | 修复 `3bace071bfad` 已包含 |
| CVE-2026-9369 | 修复 `09f85f2cf793` 已包含 |
| CVE-2026-10222 | 修复 `b944c6e821c2` 已包含 |
| CVE-2026-9366、CVE-2026-10223 | 同一关联修复 `0dee92df22bd` 已包含 |
| CVE-2026-9368 | 修复 `285bb2b9150b` 已包含 |
| CVE-2026-10221 | 合并提交 `2ca38e5df434` 已包含 |
| CVE-2026-10224 | 公告范围 `<=0.19.0`，未标修复版，关联修复 PR #73406 未合并；不宣称上游已修。Xbot 的内嵌运行路径不启动 Hermes 飞书网关。 |
