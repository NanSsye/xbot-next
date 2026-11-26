# 项目规则（xbot-next）

本项目开发规范以全局 `~/.config/ai-rules/AGENTS.md` 为准（含 SDD + 产品知识图谱 + 强制落盘），本文件只写项目特有约定，工具为
`python3 ~/.claude/skills/product-graph/pg.py`（简写 `pg`）。

## 新对话开工三步
1. `pg context`：恢复当前任务、下一步、阻塞项
2. `pg search "<问题>"`：先查图谱再作答
3. 按 `specs/<当前feature>/tasks.md` 的"下一步"继续

## 项目特有约定
- 源码目录：<!-- 例如 frontend/ = 前端，backend/ = 后端 -->
- 其他：
