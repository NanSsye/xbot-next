from xbot.agent.wiki import WikiStore


def test_wiki_store_bootstrap_query_and_lint(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")

    boot = wiki.bootstrap("xbot")
    assert boot["success"] is True
    assert (tmp_path / "wiki" / "xbot" / "schema.md").exists()
    assert (tmp_path / "wiki" / "xbot" / "pages" / "architecture.md").exists()

    wrote = wiki.write_page(
        wiki="xbot",
        page="memory-system",
        content="# Memory System\n\nShort-term memory is compressed before context overflow.",
    )
    assert wrote["success"] is True

    result = wiki.query(wiki="xbot", query="compressed memory", limit=3)
    assert result["success"] is True
    assert result["matches"][0]["page"] == "memory-system"
    assert "Short-term memory" in result["context"]

    lint = wiki.lint("xbot")
    assert lint["success"] is True
    assert lint["issues"] == []


def test_wiki_store_ingest_creates_raw_and_page(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")

    result = wiki.ingest(wiki="xbot", topic="Project Notes", text="xbot wiki stores Markdown as source truth.")

    assert result["success"] is True
    assert result["page"] == "project-notes"
    assert (tmp_path / "wiki" / "xbot" / "raw").exists()
    assert "source truth" in (tmp_path / "wiki" / "xbot" / "pages" / "project-notes.md").read_text(
        encoding="utf-8"
    )


def test_wiki_store_rejects_path_escape(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")

    try:
        wiki.bootstrap("../bad")
    except ValueError as exc:
        assert "wiki must match" in str(exc)
    else:
        raise AssertionError("expected invalid wiki name to fail")


def test_wiki_second_stage_merge_links_digest_and_index(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    wiki.write_page(
        wiki="xbot",
        page="memory-system",
        content="# Memory System\n\nWiki memory should be Markdown source truth. Agent memory should be compact.",
    )
    wiki.write_page(
        wiki="xbot",
        page="memory-architecture",
        content="# Memory Architecture\n\nWiki memory should be Markdown source truth. Short-term memory should compress.",
    )

    merge = wiki.manage({"action": "suggest_merge", "wiki": "xbot", "pages": ["memory-system", "memory-architecture"]})
    assert merge["success"] is True
    assert merge["proposals"]
    assert (tmp_path / "wiki" / "xbot" / "merge-suggestions.md").exists()

    dry_links = wiki.manage({"action": "maintain_links", "wiki": "xbot", "page": "memory-system"})
    assert dry_links["dry_run"] is True
    assert dry_links["updates"][0]["related"][0]["page"] == "memory-architecture"
    assert "## Related" not in (tmp_path / "wiki" / "xbot" / "pages" / "memory-system.md").read_text(
        encoding="utf-8"
    )

    links = wiki.manage({"action": "maintain_links", "wiki": "xbot", "page": "memory-system", "dry_run": False})
    assert links["dry_run"] is False
    assert "## Related" in (tmp_path / "wiki" / "xbot" / "pages" / "memory-system.md").read_text(encoding="utf-8")

    digest = wiki.manage(
        {"action": "digest", "wiki": "xbot", "topic": "memory", "query": "Markdown memory", "page": "memory-digest"}
    )
    assert digest["success"] is True
    assert digest["page"] == "memory-digest"
    assert (tmp_path / "wiki" / "xbot" / "pages" / "memory-digest.md").exists()

    index = wiki.manage({"action": "rebuild_index", "wiki": "xbot"})
    assert index["success"] is True
    assert index["pages"] >= 2
    assert (tmp_path / "wiki" / "xbot" / "derived" / "search-index.json").exists()


def test_wiki_second_stage_conflict_detection(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    wiki.write_page(wiki="xbot", page="runtime-a", content="# Runtime A\n\n- Shell execution should be enabled.")
    wiki.write_page(wiki="xbot", page="runtime-b", content="# Runtime B\n\n- Shell execution must not be enabled.")

    result = wiki.manage({"action": "detect_conflicts", "wiki": "xbot", "query": "Shell execution"})

    assert result["success"] is True
    assert result["conflicts"]
    assert result["conflicts"][0]["topic"] == "shell execution"
    assert (tmp_path / "wiki" / "xbot" / "conflicts.md").exists()
