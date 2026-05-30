# Agent-Owned Skill Templates

This directory contains templates for xbot self-evolution.

Agent-created skills should live under:

```text
skills/.agent/<skill-name>/
  skill.toml
  SKILL.md
  references/
  templates/
  scripts/
  assets/
```

Only these paths are allowed for `skill.manage`:

- `SKILL.md`
- `references/`
- `templates/`
- `scripts/`
- `assets/`

The curator writes dry-run reports to `skills/.agent/.curator/`.
