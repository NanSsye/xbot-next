# xbot Self Evolution

Use this skill when maintaining xbot's long-term memory, agent-owned skills, or curator reports.

## Memory Model

- `data/agent/memories/USER.md` stores stable user preferences, corrections, and communication style.
- `data/agent/memories/MEMORY.md` stores stable project facts, environment facts, conventions, and tool quirks.
- Separate memory entries with a line containing only `§`.
- Do not store secrets, raw logs, or temporary task progress.

## Procedural Memory

- Agent-owned procedural skills live under `skills/.agent/<skill-name>/`.
- Prefer patching an existing agent-owned skill before creating a new narrow skill.
- Keep each skill focused on a reusable workflow.
- Allowed managed paths are `SKILL.md`, `references/`, `templates/`, `scripts/`, and `assets/`.

## Curator Workflow

1. Run `/curator report` to generate a dry-run report.
2. Review proposals in `skills/.agent/.curator/latest.json`.
3. Apply only selected proposals with `/curator apply <proposal_id>`.
4. Use `/curator report --no-llm` when only deterministic rule and duplicate checks are desired.

## Guardrails

- Curator reports are proposals, not automatic edits.
- Merge proposals should preserve the better skill and archive the source skill.
- Pinned skills must not be archived by routine cleanup.
