# Curator Reports

Curator dry-run reports are written here.

Generated files:

- `latest.json`: newest report
- `<report-id>.json`: report history

Reports contain proposed actions only. Nothing is applied until a user runs:

```text
/curator apply <proposal_id>
```

or calls:

```text
POST /api/v1/agent/curator/apply
```
