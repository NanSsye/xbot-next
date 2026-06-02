from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.request import Request, urlopen

WIKI_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")

SCHEMA_TEMPLATE = """# xbot Wiki Schema

This directory is a file-based knowledge base maintained by xbot.

Rules:
- Markdown files are the source of truth.
- `index.md` is a generated navigation/search index.
- `log.md` records important maintenance events.
- `pages/` stores curated knowledge pages.
- `raw/` stores copied source material from ingest operations.
- RAG/vector search may be added later only as a derived cache, not as the source of truth.

Page guidance:
- Keep pages factual, compact, and linkable.
- Prefer stable architecture, design decisions, operating procedures, research notes, and project knowledge.
- Do not store secrets, temporary chat state, or raw private logs.
"""


@dataclass(slots=True)
class WikiPage:
    slug: str
    path: Path
    title: str
    excerpt: str


class WikiStore:
    def __init__(
        self,
        directory: str | Path = "data/hermes/wiki",
        *,
        default_wiki: str = "xbot",
        query_max_chars: int = 12000,
    ) -> None:
        self.directory = Path(directory)
        self.default_wiki = self._normalize_wiki(default_wiki)
        self.query_max_chars = query_max_chars

    def manage(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip()
        wiki = self._normalize_wiki(str(payload.get("wiki") or self.default_wiki))
        if action == "bootstrap":
            return self.bootstrap(wiki)
        if action == "ingest":
            return self.ingest(
                wiki=wiki,
                topic=str(payload.get("topic") or ""),
                source=str(payload.get("source") or ""),
                text=str(payload.get("text") or ""),
            )
        if action == "query":
            return self.query(
                wiki=wiki,
                query=str(payload.get("query") or ""),
                limit=int(payload.get("limit") or 5),
            )
        if action == "read_page":
            return self.read_page(wiki=wiki, page=str(payload.get("page") or ""))
        if action == "write_page":
            return self.write_page(
                wiki=wiki,
                page=str(payload.get("page") or ""),
                content=str(payload.get("content") or ""),
                title=str(payload.get("title") or ""),
            )
        if action == "append_page":
            return self.append_page(
                wiki=wiki,
                page=str(payload.get("page") or ""),
                content=str(payload.get("content") or ""),
                title=str(payload.get("title") or ""),
            )
        if action == "suggest_merge":
            return self.suggest_merge(
                wiki=wiki,
                query=str(payload.get("query") or ""),
                pages=payload.get("pages") if isinstance(payload.get("pages"), list) else None,
                limit=int(payload.get("limit") or 10),
            )
        if action == "maintain_links":
            return self.maintain_links(
                wiki=wiki,
                page=str(payload.get("page") or ""),
                dry_run=bool(payload.get("dry_run", True)),
            )
        if action == "detect_conflicts":
            return self.detect_conflicts(wiki=wiki, query=str(payload.get("query") or ""))
        if action == "digest":
            return self.digest(
                wiki=wiki,
                topic=str(payload.get("topic") or payload.get("query") or ""),
                query=str(payload.get("query") or payload.get("topic") or ""),
                page=str(payload.get("page") or ""),
                dry_run=bool(payload.get("dry_run", True)),
                limit=int(payload.get("limit") or 8),
            )
        if action == "rebuild_index":
            return self.rebuild_derived_index(wiki)
        if action == "update_index":
            return self.update_index(wiki)
        if action == "lint":
            return self.lint(wiki)
        if action == "log":
            return self.log(wiki=wiki, message=str(payload.get("message") or ""))
        raise ValueError(
            "action must be bootstrap, ingest, query, read_page, write_page, append_page, "
            "suggest_merge, maintain_links, detect_conflicts, digest, rebuild_index, update_index, lint, or log"
        )

    def bootstrap(self, wiki: str | None = None) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki or self.default_wiki)
        root = self._wiki_root(wiki)
        pages = root / "pages"
        raw = root / "raw"
        pages.mkdir(parents=True, exist_ok=True)
        raw.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        files = {
            "schema.md": SCHEMA_TEMPLATE,
            "index.md": self._render_index(wiki, []),
            "log.md": f"# {wiki} Wiki Log\n\n",
            "merge-suggestions.md": "# Merge Suggestions\n\nGenerated merge suggestions and review notes.\n",
            "conflicts.md": "# Conflicts\n\nGenerated conflict detection notes.\n",
            "pages/architecture.md": "# Architecture\n\nProject architecture notes.\n",
            "pages/decisions.md": "# Decisions\n\nDurable design decisions.\n",
            "pages/plugins.md": "# Plugins\n\nPlugin and skill ecosystem notes.\n",
            "pages/memory-system.md": "# Memory System\n\nLong-term memory, short-term working memory, and wiki knowledge notes.\n",
        }
        for relative, content in files.items():
            path = root / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                created.append(relative)
        self.update_index(wiki)
        if created:
            self.log(wiki=wiki, message=f"bootstrap created {len(created)} files")
        return {"success": True, "wiki": wiki, "root": str(root), "created": created}

    def ingest(self, *, wiki: str, topic: str, source: str = "", text: str = "") -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        content, source_label = self._load_source(source=source, text=text)
        if not content.strip():
            return {"success": False, "error": "source or text content is required"}
        slug = self._slug(topic or source_label or "note")
        root = self._wiki_root(wiki)
        raw_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{slug}.md"
        raw_path = root / "raw" / raw_name
        raw_path.write_text(content, encoding="utf-8")
        page_path = self._page_path(wiki, slug)
        title = self._title(topic or slug)
        section = (
            f"\n\n## Ingested {datetime.utcnow().isoformat(timespec='seconds')}Z\n\n"
            f"Source: `{source_label}`\n\n"
            f"{content.strip()}\n"
        )
        if page_path.exists():
            page_path.write_text(page_path.read_text(encoding="utf-8").rstrip() + section, encoding="utf-8")
        else:
            page_path.write_text(f"# {title}{section}", encoding="utf-8")
        self.update_index(wiki)
        self.log(wiki=wiki, message=f"ingested {source_label} into pages/{slug}.md")
        return {
            "success": True,
            "wiki": wiki,
            "page": slug,
            "page_path": str(page_path),
            "raw_path": str(raw_path),
            "chars": len(content),
        }

    def query(self, *, wiki: str, query: str, limit: int = 5) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        query = query.strip()
        if not query:
            return {"success": False, "error": "query is required"}
        terms = self._terms(query)
        matches: list[dict[str, Any]] = []
        for page in self._pages(wiki):
            text = page.path.read_text(encoding="utf-8")
            score = self._score(text, page.slug, terms)
            if score <= 0:
                continue
            matches.append(
                {
                    "page": page.slug,
                    "path": str(page.path),
                    "title": page.title,
                    "score": score,
                    "snippet": self._snippet(text, terms),
                }
            )
        matches.sort(key=lambda item: (-int(item["score"]), str(item["page"])))
        matches = matches[: max(1, min(limit, 20))]
        rendered = "\n\n".join(f"## {item['title']}\n{item['snippet']}" for item in matches)
        if len(rendered) > self.query_max_chars:
            rendered = rendered[: self.query_max_chars].rstrip() + "\n..."
        return {"success": True, "wiki": wiki, "query": query, "matches": matches, "context": rendered}

    def read_page(self, *, wiki: str, page: str) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        path = self._page_path(wiki, self._slug(page))
        if not path.exists():
            return {"success": False, "error": f"page not found: {page}"}
        return {"success": True, "wiki": wiki, "page": path.stem, "path": str(path), "content": path.read_text(encoding="utf-8")}

    def write_page(self, *, wiki: str, page: str, content: str, title: str = "") -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        slug = self._slug(page)
        content = content.strip()
        if not content:
            return {"success": False, "error": "content is required"}
        if not content.startswith("# "):
            content = f"# {self._title(title or slug)}\n\n{content}"
        path = self._page_path(wiki, slug)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        self.update_index(wiki)
        self.log(wiki=wiki, message=f"wrote pages/{slug}.md")
        return {"success": True, "wiki": wiki, "page": slug, "path": str(path), "chars": len(content)}

    def append_page(self, *, wiki: str, page: str, content: str, title: str = "") -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        slug = self._slug(page)
        content = content.strip()
        if not content:
            return {"success": False, "error": "content is required"}
        path = self._page_path(wiki, slug)
        if not path.exists():
            path.write_text(f"# {self._title(title or slug)}\n", encoding="utf-8")
        path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n" + content + "\n", encoding="utf-8")
        self.update_index(wiki)
        self.log(wiki=wiki, message=f"appended pages/{slug}.md")
        return {"success": True, "wiki": wiki, "page": slug, "path": str(path), "chars": len(content)}

    def suggest_merge(
        self,
        *,
        wiki: str,
        query: str = "",
        pages: list[Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        selected = self._selected_pages(wiki, query=query, pages=pages)
        proposals: list[dict[str, Any]] = []
        for idx, left in enumerate(selected):
            left_text = left.path.read_text(encoding="utf-8")
            left_terms = set(self._terms(left_text))
            for right in selected[idx + 1 :]:
                right_text = right.path.read_text(encoding="utf-8")
                right_terms = set(self._terms(right_text))
                shared = sorted(left_terms & right_terms)
                if not shared:
                    continue
                smaller = max(1, min(len(left_terms), len(right_terms)))
                score = round((len(shared) / smaller) * 100)
                title_match = self._similar_title(left.title, right.title)
                if score < 18 and not title_match:
                    continue
                target, source = (left, right) if len(left_text) >= len(right_text) else (right, left)
                proposals.append(
                    {
                        "target": target.slug,
                        "source": source.slug,
                        "score": score + (20 if title_match else 0),
                        "reason": self._merge_reason(left, right, shared, title_match),
                        "shared_terms": shared[:20],
                        "suggested_action": "review_then_merge_source_into_target",
                    }
                )
        proposals.sort(key=lambda item: (-int(item["score"]), str(item["target"]), str(item["source"])))
        proposals = proposals[: max(1, min(limit, 50))]
        root = self._wiki_root(wiki)
        path = root / "merge-suggestions.md"
        path.write_text(self._render_merge_report(wiki, proposals), encoding="utf-8")
        self.log(wiki=wiki, message=f"generated {len(proposals)} merge suggestions")
        return {"success": True, "wiki": wiki, "proposals": proposals, "path": str(path)}

    def maintain_links(self, *, wiki: str, page: str = "", dry_run: bool = True) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        pages = self._pages(wiki)
        selected = [item for item in pages if not page or item.slug == self._slug(page)]
        updates: list[dict[str, Any]] = []
        for item in selected:
            related = self._related_pages(item, [candidate for candidate in pages if candidate.slug != item.slug])
            if not related:
                continue
            text = item.path.read_text(encoding="utf-8")
            next_text = self._replace_related_block(text, self._render_related_block(related))
            updates.append(
                {
                    "page": item.slug,
                    "related": [{"page": rel["page"].slug, "score": rel["score"]} for rel in related],
                    "changed": next_text != text,
                }
            )
            if not dry_run and next_text != text:
                item.path.write_text(next_text, encoding="utf-8")
        if not dry_run:
            self.update_index(wiki)
            self.log(wiki=wiki, message=f"maintained cross-links for {len(updates)} pages")
        return {"success": True, "wiki": wiki, "dry_run": dry_run, "updates": updates}

    def detect_conflicts(self, *, wiki: str, query: str = "") -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        claims: dict[str, list[dict[str, str]]] = {}
        for page in self._selected_pages(wiki, query=query):
            for line in page.path.read_text(encoding="utf-8").splitlines():
                claim_type = self._claim_type(line)
                if not claim_type:
                    continue
                key = self._claim_key(line)
                if key:
                    claims.setdefault(key, []).append({"page": page.slug, "type": claim_type, "text": line.strip()})
        conflicts = []
        for key, items in claims.items():
            types = {item["type"] for item in items}
            if "positive" in types and "negative" in types:
                conflicts.append({"topic": key, "claims": items})
        conflicts.sort(key=lambda item: str(item["topic"]))
        root = self._wiki_root(wiki)
        path = root / "conflicts.md"
        path.write_text(self._render_conflict_report(wiki, conflicts), encoding="utf-8")
        self.log(wiki=wiki, message=f"detected {len(conflicts)} possible wiki conflicts")
        return {"success": True, "wiki": wiki, "conflicts": conflicts, "path": str(path)}

    def digest(
        self,
        *,
        wiki: str,
        topic: str,
        query: str,
        page: str = "",
        dry_run: bool = True,
        limit: int = 8,
    ) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        self.bootstrap(wiki)
        topic = topic.strip()
        query = query.strip()
        if not topic and not query:
            return {"success": False, "error": "topic or query is required"}
        query_result = self.query(wiki=wiki, query=query or topic, limit=limit)
        matches = query_result.get("matches", [])
        lines = [
            f"# {self._title(topic or query)} Digest",
            "",
            f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z",
            f"Query: `{query or topic}`",
            "",
            "## Summary",
            "",
            "This digest is generated from current wiki pages. Review before treating it as authoritative.",
            "",
            "## Source Notes",
            "",
        ]
        if not matches:
            lines.append("- No matching wiki pages.")
        for match in matches:
            lines.extend(
                [
                    f"### {match['title']}",
                    "",
                    f"Source: [pages/{match['page']}.md](pages/{match['page']}.md)",
                    "",
                    str(match["snippet"]).strip(),
                    "",
                ]
            )
        content = "\n".join(lines).rstrip() + "\n"
        result: dict[str, Any] = {"success": True, "wiki": wiki, "topic": topic or query, "dry_run": dry_run, "matches": matches, "content": content}
        if not dry_run or page:
            slug = self._slug(page or f"digest-{topic or query}")
            path = self._page_path(wiki, slug)
            path.write_text(content, encoding="utf-8")
            self.update_index(wiki)
            self.log(wiki=wiki, message=f"wrote digest pages/{slug}.md")
            result.update({"page": slug, "path": str(path)})
        return result

    def rebuild_derived_index(self, wiki: str | None = None) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki or self.default_wiki)
        self.bootstrap(wiki)
        root = self._wiki_root(wiki)
        derived = root / "derived"
        derived.mkdir(parents=True, exist_ok=True)
        pages = []
        inverted: dict[str, list[str]] = {}
        for page in self._pages(wiki):
            text = page.path.read_text(encoding="utf-8")
            terms = sorted(set(self._terms(text)))
            pages.append({"page": page.slug, "title": page.title, "path": f"pages/{page.slug}.md", "terms": terms[:300], "chars": len(text), "excerpt": page.excerpt})
            for term in terms:
                inverted.setdefault(term, []).append(page.slug)
        payload = {
            "schema": "xbot-wiki-derived-index-v1",
            "wiki": wiki,
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "Markdown pages are authoritative; this index is rebuildable.",
            "pages": pages,
            "inverted": {term: sorted(set(slugs)) for term, slugs in sorted(inverted.items())},
        }
        path = derived / "search-index.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(wiki=wiki, message=f"rebuilt derived search index with {len(pages)} pages")
        return {"success": True, "wiki": wiki, "path": str(path), "pages": len(pages), "terms": len(inverted)}

    def update_index(self, wiki: str | None = None) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki or self.default_wiki)
        root = self._wiki_root(wiki)
        (root / "pages").mkdir(parents=True, exist_ok=True)
        pages = self._pages(wiki)
        index = self._render_index(wiki, pages)
        (root / "index.md").write_text(index, encoding="utf-8")
        return {"success": True, "wiki": wiki, "pages": len(pages), "path": str(root / "index.md")}

    def lint(self, wiki: str | None = None) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki or self.default_wiki)
        self.bootstrap(wiki)
        issues: list[dict[str, str]] = []
        root = self._wiki_root(wiki)
        for relative in ("schema.md", "index.md", "log.md", "pages"):
            if not (root / relative).exists():
                issues.append({"level": "error", "path": relative, "message": "missing"})
        for page in self._pages(wiki):
            text = page.path.read_text(encoding="utf-8")
            if not text.lstrip().startswith("# "):
                issues.append({"level": "warning", "path": str(page.path), "message": "page should start with H1"})
            if self._blocked_content(text):
                issues.append({"level": "error", "path": str(page.path), "message": "possible secret or prompt-injection text"})
            for link in re.findall(r"\]\((pages/[^)]+\.md)\)", text):
                if not (root / link).exists():
                    issues.append({"level": "warning", "path": str(page.path), "message": f"broken wiki link: {link}"})
        return {"success": not any(item["level"] == "error" for item in issues), "wiki": wiki, "issues": issues}

    def log(self, *, wiki: str, message: str) -> dict[str, Any]:
        wiki = self._normalize_wiki(wiki)
        message = message.strip()
        if not message:
            return {"success": False, "error": "message is required"}
        root = self._wiki_root(wiki)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "log.md"
        if not path.exists():
            path.write_text(f"# {wiki} Wiki Log\n\n", encoding="utf-8")
        entry = f"- {datetime.utcnow().isoformat(timespec='seconds')}Z: {message}\n"
        path.write_text(path.read_text(encoding="utf-8") + entry, encoding="utf-8")
        return {"success": True, "wiki": wiki, "path": str(path)}

    def _wiki_root(self, wiki: str) -> Path:
        wiki = self._normalize_wiki(wiki)
        root = (self.directory / wiki).resolve()
        base = self.directory.resolve()
        if base not in root.parents and root != base:
            raise ValueError("wiki path escapes wiki directory")
        return root

    def _page_path(self, wiki: str, slug: str) -> Path:
        slug = self._slug(slug)
        return self._wiki_root(wiki) / "pages" / f"{slug}.md"

    def _pages(self, wiki: str) -> list[WikiPage]:
        pages_dir = self._wiki_root(wiki) / "pages"
        if not pages_dir.exists():
            return []
        pages: list[WikiPage] = []
        for path in sorted(pages_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = self._extract_title(text) or self._title(path.stem)
            pages.append(WikiPage(slug=path.stem, path=path, title=title, excerpt=self._excerpt(text)))
        return pages

    def _selected_pages(self, wiki: str, *, query: str = "", pages: list[Any] | None = None) -> list[WikiPage]:
        all_pages = self._pages(wiki)
        if pages:
            wanted = {self._slug(str(item)) for item in pages}
            return [item for item in all_pages if item.slug in wanted]
        query = query.strip()
        if not query:
            return all_pages
        matches = self.query(wiki=wiki, query=query, limit=50).get("matches", [])
        wanted = {str(item.get("page")) for item in matches if isinstance(item, dict)}
        return [item for item in all_pages if item.slug in wanted]

    def _load_source(self, *, source: str, text: str) -> tuple[str, str]:
        if text.strip():
            return text, "inline-text"
        source = source.strip()
        if not source:
            return "", ""
        if source.startswith(("http://", "https://")):
            request = Request(source, headers={"User-Agent": "xbot-wiki/1.0"})
            with urlopen(request, timeout=20) as response:
                content = response.read(1_000_000).decode("utf-8", errors="replace")
            return content, source
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            if any(separator in source for separator in ("/", "\\")) or Path(source).suffix:
                raise ValueError(f"source file not found: {source}")
            return source, "inline-source"
        return path.read_text(encoding="utf-8"), str(path)

    def _render_index(self, wiki: str, pages: list[WikiPage]) -> str:
        lines = [
            f"# {wiki} Wiki Index",
            "",
            "This is the generated index for the Markdown knowledge base.",
            "",
            "## Pages",
            "",
        ]
        if not pages:
            lines.append("- No pages yet.")
        for page in pages:
            lines.append(f"- [{page.title}](pages/{page.slug}.md) - {page.excerpt}")
        lines.extend(
            [
                "",
                "## Maintenance",
                "",
                "- Run `wiki.manage action=update_index` after structural edits.",
                "- Use `wiki.manage action=query` before answering from project knowledge.",
                "- Keep Markdown files authoritative; derived RAG/vector indexes must be rebuildable.",
                "",
            ]
        )
        return "\n".join(lines)

    def _related_pages(self, page: WikiPage, candidates: list[WikiPage]) -> list[dict[str, Any]]:
        page_terms = set(self._terms(page.path.read_text(encoding="utf-8")))
        related = []
        for candidate in candidates:
            candidate_terms = set(self._terms(candidate.path.read_text(encoding="utf-8")))
            shared = page_terms & candidate_terms
            if not shared:
                continue
            score = len(shared) + (10 if self._similar_title(page.title, candidate.title) else 0)
            if score >= 3:
                related.append({"page": candidate, "score": score, "shared_terms": sorted(shared)[:10]})
        related.sort(key=lambda item: (-int(item["score"]), item["page"].slug))
        return related[:5]

    def _render_related_block(self, related: list[dict[str, Any]]) -> str:
        lines = ["## Related", ""]
        for item in related:
            page = item["page"]
            lines.append(f"- [{page.title}](pages/{page.slug}.md) - related score {item['score']}")
        return "\n".join(lines).rstrip() + "\n"

    def _replace_related_block(self, text: str, related_block: str) -> str:
        pattern = re.compile(r"\n## Related\n.*?(?=\n## |\Z)", re.DOTALL)
        if pattern.search(text):
            return pattern.sub("\n" + related_block.rstrip() + "\n", text).rstrip() + "\n"
        return text.rstrip() + "\n\n" + related_block

    def _render_merge_report(self, wiki: str, proposals: list[dict[str, Any]]) -> str:
        lines = [f"# {wiki} Merge Suggestions", "", f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z", ""]
        if not proposals:
            lines.append("No merge candidates found.")
        for proposal in proposals:
            lines.extend(
                [
                    f"## {proposal['source']} -> {proposal['target']}",
                    "",
                    f"- Score: {proposal['score']}",
                    f"- Reason: {proposal['reason']}",
                    f"- Shared terms: {', '.join(proposal['shared_terms'])}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _render_conflict_report(self, wiki: str, conflicts: list[dict[str, Any]]) -> str:
        lines = [f"# {wiki} Conflicts", "", f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z", ""]
        if not conflicts:
            lines.append("No conflicts found.")
        for conflict in conflicts:
            lines.extend([f"## {conflict['topic']}", ""])
            for claim in conflict["claims"]:
                lines.append(f"- `{claim['page']}` {claim['type']}: {claim['text']}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _normalize_wiki(self, wiki: str) -> str:
        wiki = wiki.strip().lower()
        if not WIKI_NAME_RE.match(wiki):
            raise ValueError("wiki must match [a-z0-9][a-z0-9._-]{0,63}")
        return wiki

    def _slug(self, value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9._-]+", "-", value).strip("-._")
        if not value:
            raise ValueError("page/topic slug cannot be empty")
        value = value[:96].strip("-._")
        if not SLUG_RE.match(value):
            raise ValueError("page/topic slug must be a safe file name")
        return value

    def _terms(self, query: str) -> list[str]:
        terms = re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
        return [term for term in terms if len(term) >= 2] or [query.lower()]

    def _score(self, text: str, slug: str, terms: list[str]) -> int:
        haystack = f"{slug}\n{text}".lower()
        return sum(haystack.count(term) for term in terms)

    def _similar_title(self, left: str, right: str) -> bool:
        left_terms = set(self._terms(left))
        right_terms = set(self._terms(right))
        return bool(left_terms and right_terms and left_terms & right_terms)

    def _merge_reason(self, left: WikiPage, right: WikiPage, shared: list[str], title_match: bool) -> str:
        reason = f"{left.slug} and {right.slug} share {len(shared)} indexed terms"
        if title_match:
            reason += " and have similar titles"
        return reason + "."

    def _claim_type(self, line: str) -> str:
        lowered = line.lower()
        negative = ("must not", "do not", "deprecated", "disabled", "forbidden", "禁止", "不要", "废弃", "不可")
        positive = ("must", "should", "recommended", "enabled", "required", "必须", "应该", "推荐", "启用", "需要")
        if any(marker in lowered for marker in negative):
            return "negative"
        if any(marker in lowered for marker in positive):
            return "positive"
        return ""

    def _claim_key(self, line: str) -> str:
        cleaned = re.sub(
            r"(?i)\b(must not|do not|deprecated|disabled|forbidden|must|should|recommended|enabled|required)\b",
            " ",
            line,
        )
        cleaned = re.sub(r"(禁止|不要|废弃|不可|必须|应该|推荐|启用|需要)", " ", cleaned)
        stop = {"the", "and", "with", "this", "that", "be", "is", "are", "was", "were"}
        terms = [term for term in self._terms(cleaned) if term not in stop]
        return " ".join(terms[:4])

    def _snippet(self, text: str, terms: list[str]) -> str:
        lowered = text.lower()
        index = min((lowered.find(term) for term in terms if lowered.find(term) >= 0), default=0)
        start = max(0, index - 220)
        end = min(len(text), index + 780)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet += "..."
        return snippet

    def _extract_title(self, text: str) -> str:
        match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
        return match.group(1).strip() if match else ""

    def _excerpt(self, text: str) -> str:
        text = re.sub(r"(?m)^#.+$", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return (text[:117] + "...") if len(text) > 120 else text

    def _title(self, slug: str) -> str:
        return " ".join(part.capitalize() for part in re.split(r"[-_]+", slug) if part)

    def _blocked_content(self, content: str) -> bool:
        lowered = content.lower()
        blocked = ("password", "api_key", "private_key", "secret", "ignore previous", "system prompt")
        return any(pattern in lowered for pattern in blocked)
