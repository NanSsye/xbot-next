# xbot Wiki Schema

This directory is the first-phase file-based knowledge base for xbot.

Rules:
- Markdown files are the source of truth.
- `index.md` is a generated navigation/search index.
- `log.md` records maintenance events.
- `merge-suggestions.md` records generated merge candidates for human/agent review.
- `conflicts.md` records generated conflict detection reports.
- `pages/` stores curated knowledge pages.
- `raw/` may store copied source material from ingest operations, but generated raw files are not tracked by default.
- `derived/` may store rebuildable search/RAG index artifacts, but generated derived files are not tracked by default.
- RAG/vector search can be added later only as a derived cache.

Do not store secrets, temporary chat state, or raw private logs here.
