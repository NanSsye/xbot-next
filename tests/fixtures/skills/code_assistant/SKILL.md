# Code Assistant Skill

Use this skill when the agent needs to inspect or modify code in the configured workspace.

Rules:

- Read relevant files before editing.
- Keep changes scoped to the requested task.
- Use the filesystem tools instead of bypassing the tool executor.
- Respect agent policy and workspace boundaries.
- Summarize changed files and verification results when done.

