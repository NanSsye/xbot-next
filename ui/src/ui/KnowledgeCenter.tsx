import {
  Archive,
  BookOpenText,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Download,
  FileText,
  FolderTree,
  History,
  Pause,
  Play,
  RefreshCw,
  Search,
} from "lucide-react";
import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { KnowledgeBase, KnowledgePage, KnowledgeRun } from "../types";

function formatTime(value?: string | null): string {
  if (!value) return "尚未运行";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function categoryLabel(path: string): string {
  if (!path.includes("/")) return path === "00-首页.md" ? "首页" : "根目录";
  return path.split("/", 1)[0] || "未分类";
}

function errorMessage(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : String(reason);
  return message === "knowledge page not found" ? "页面已更新或不存在，请刷新目录后重试。" : message;
}

export function KnowledgeCenter() {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [pages, setPages] = useState<KnowledgePage[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [content, setContent] = useState("");
  const [runs, setRuns] = useState<KnowledgeRun[]>([]);
  const [query, setQuery] = useState("");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const baseRequestRef = useRef(0);
  const selected = bases.find((item) => item.conversation_id === selectedId);

  async function loadBases() {
    const next = await api.knowledgeBases();
    setBases(next);
    setSelectedId((current) => current || next[0]?.conversation_id || "");
  }

  async function loadBase(id: string, search = query) {
    if (!id) return;
    const requestId = ++baseRequestRef.current;
    const [nextPages, nextRuns] = await Promise.all([api.knowledgePages(id, search), api.knowledgeRuns(id)]);
    if (requestId !== baseRequestRef.current) return;
    setPages(nextPages);
    setRuns(nextRuns);
    setSelectedPath((current) => nextPages.some((page) => page.relative_path === current) ? current : nextPages[0]?.relative_path || "");
    setError("");
  }

  useEffect(() => {
    loadBases().catch((reason) => setError(errorMessage(reason)));
    const timer = window.setInterval(() => void loadBases().catch(() => undefined), 10_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setPages([]);
    setRuns([]);
    setSelectedPath("");
    setContent("");
    setExpandedCategories(new Set());
    loadBase(selectedId, "").catch((reason) => setError(errorMessage(reason)));
  }, [selectedId]);

  useEffect(() => {
    if (!selectedPath) return;
    const category = categoryLabel(selectedPath);
    setExpandedCategories((current) => current.has(category) ? current : new Set(current).add(category));
  }, [selectedPath]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedId || !selectedPath) {
      setContent("");
      return () => { cancelled = true; };
    }
    api.knowledgePage(selectedId, selectedPath)
      .then((result) => {
        if (cancelled) return;
        setContent(result.content);
        setError("");
      })
      .catch((reason) => { if (!cancelled) setError(errorMessage(reason)); });
    return () => { cancelled = true; };
  }, [selectedId, selectedPath]);

  const grouped = useMemo(() => {
    const result = new Map<string, KnowledgePage[]>();
    for (const page of pages) {
      const category = categoryLabel(page.relative_path);
      result.set(category, [...(result.get(category) || []), page]);
    }
    return [...result.entries()];
  }, [pages]);

  async function act(name: string, action: () => Promise<unknown>) {
    setBusy(name);
    setError("");
    try {
      await action();
      await loadBases();
      await loadBase(selectedId);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy("");
    }
  }

  function selectBase(id: string) {
    if (id === selectedId) return;
    baseRequestRef.current += 1;
    setError("");
    setPages([]);
    setRuns([]);
    setSelectedPath("");
    setContent("");
    setSelectedId(id);
  }

  function openWikiLink(label: string) {
    const normalized = label.split("|").pop()?.trim() || label;
    const page = pages.find((item) => item.title === normalized || item.relative_path.replace(/\.md$/, "") === label.split("|")[0]);
    if (page) setSelectedPath(page.relative_path);
  }

  function toggleCategory(category: string) {
    setExpandedCategories((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  return (
    <section className="knowledge-shell" aria-label="群聊知识库">
      <aside className="knowledge-groups">
        <header className="knowledge-pane-head">
          <div><BookOpenText size={18} /><strong>群知识库</strong></div>
          <button type="button" className="knowledge-icon-button" onClick={() => void loadBases()} title="刷新知识库列表"><RefreshCw size={16} /></button>
        </header>
        <p className="knowledge-pane-note">每个群独立提炼，只发布可复用的长期知识。</p>
        <div className="knowledge-group-list">
          {bases.length ? bases.map((base) => (
            <button key={base.conversation_id} type="button" className={`knowledge-group ${selectedId === base.conversation_id ? "is-active" : ""}`} onClick={() => selectBase(base.conversation_id)}>
              <span className="knowledge-group__icon"><Archive size={17} /></span>
              <span className="knowledge-group__copy"><strong>{base.title}</strong><small>{base.platform} · {base.page_count} 页 · {base.source_count} 条有效来源</small></span>
              <span className={`knowledge-status-dot is-${base.status}`} aria-label={base.status} />
            </button>
          )) : <div className="knowledge-empty"><Archive size={28} /><strong>还没有群知识库</strong><span>收到群消息后会自动建立。</span></div>}
        </div>
      </aside>

      <aside className="knowledge-index">
        <header className="knowledge-pane-head">
          <div><FolderTree size={18} /><strong>目录</strong></div>
          <span>{pages.length} 页</span>
        </header>
        <form className="knowledge-search" onSubmit={(event) => { event.preventDefault(); void loadBase(selectedId); }}>
          <Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题与摘要" aria-label="搜索知识库" />
          <button type="submit">搜索</button>
        </form>
        <div className="knowledge-tree">
          {grouped.length ? grouped.map(([category, items], groupIndex) => {
            const expanded = expandedCategories.has(category);
            const groupId = `knowledge-tree-group-${groupIndex}`;
            return (
            <section key={category} className="knowledge-tree-group">
              <h3>
                <button type="button" className="knowledge-tree-group__toggle" aria-expanded={expanded} aria-controls={groupId} onClick={() => toggleCategory(category)}>
                  <span>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}{category}</span>
                  <span>{items.length}</span>
                </button>
              </h3>
              <div id={groupId} className="knowledge-tree-group__items" hidden={!expanded}>
                {items.map((page) => (
                  <button key={page.relative_path} type="button" className={selectedPath === page.relative_path ? "is-active" : ""} onClick={() => setSelectedPath(page.relative_path)}>
                    <FileText size={15} /><span><strong>{page.title}</strong><small>{page.summary || "暂无摘要"}</small></span><ChevronRight size={14} />
                  </button>
                ))}
              </div>
            </section>
            );
          }) : <div className="knowledge-empty knowledge-empty--compact"><FileText size={25} /><strong>暂无页面</strong><span>点击“立即学习”整理历史消息。</span></div>}
        </div>
      </aside>

      <main className="knowledge-reader">
        {error ? <div className="knowledge-error">{error}</div> : null}
        {selected ? (
          <>
            <header className="knowledge-toolbar">
              <div className="knowledge-title-block">
                <span className={`knowledge-state is-${selected.status}`}>{selected.status === "running" ? <RefreshCw size={14} /> : selected.enabled ? <CheckCircle2 size={14} /> : <Pause size={14} />}{selected.status === "running" ? "正在学习" : selected.enabled ? "自动学习已开启" : "已暂停"}</span>
                <h1>{selected.title}</h1>
                <p><Clock3 size={14} />上次 {formatTime(selected.last_run_at)} · 下次 {selected.enabled ? formatTime(selected.next_run_at) : "暂停中"}</p>
              </div>
              <div className="knowledge-actions">
                <button type="button" className="is-primary" disabled={busy !== "" || selected.status === "running"} onClick={() => void act("run", () => api.runKnowledgeBase(selectedId))}><Play size={16} />立即学习</button>
                <button type="button" disabled={busy !== ""} onClick={() => void act("toggle", () => api.updateKnowledgeBase(selectedId, !selected.enabled))}>{selected.enabled ? <Pause size={16} /> : <Play size={16} />}{selected.enabled ? "暂停" : "启用"}</button>
                <button type="button" disabled={busy !== ""} onClick={() => void act("download", () => api.downloadKnowledgeVault(selectedId))}><Download size={16} />下载 Vault</button>
              </div>
            </header>
            <div className="knowledge-metrics" aria-label="知识库统计">
              <span><FileText size={15} /><b>{selected.page_count}</b> 页面</span>
              <span><Archive size={15} /><b>{selected.file_count}</b> 文件</span>
              <span><Archive size={15} /><b>{selected.source_count}</b> 来源</span>
              <span><Bot size={15} /><b>12h</b> 周期</span>
            </div>
            <article className="knowledge-document">
              {content ? <MarkdownDocument content={content} onWikiLink={openWikiLink} /> : <div className="knowledge-empty"><BookOpenText size={34} /><strong>选择一篇知识页面</strong><span>正文、来源与双向链接会显示在这里。</span></div>}
            </article>
            <details className="knowledge-runs">
              <summary><History size={16} />最近学习记录 <span>{runs.length}</span></summary>
              <div>{runs.slice(0, 8).map((run) => <p key={run.id}><span className={`knowledge-status-dot is-${run.status}`} /><b>{formatTime(run.started_at)}</b><span>{run.message_count} 条消息 · {run.file_count} 个文件 · 更新 {run.page_change_count} 页</span>{run.error ? <em>{run.error}</em> : null}</p>)}</div>
            </details>
          </>
        ) : <div className="knowledge-empty"><Archive size={36} /><strong>选择一个群</strong><span>查看它独立的知识库与学习记录。</span></div>}
      </main>
    </section>
  );
}

function MarkdownDocument({ content, onWikiLink }: { content: string; onWikiLink: (label: string) => void }) {
  const body = content.replace(/^---\n[\s\S]*?\n---\n/, "").trim();
  const lines = body.split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trimEnd();
    if (!line.trim()) { index += 1; continue; }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const headingContent = inlineMarkdown(heading[2], onWikiLink);
      blocks.push(level === 1 ? <h2 key={index}>{headingContent}</h2> : level === 2 ? <h3 key={index}>{headingContent}</h3> : <h4 key={index}>{headingContent}</h4>);
      index += 1; continue;
    }
    if (line.startsWith("> [!")) {
      const callout = [line.replace(/^>\s?/, "")];
      index += 1;
      while (index < lines.length && lines[index].startsWith(">")) { callout.push(lines[index].replace(/^>\s?/, "")); index += 1; }
      blocks.push(<aside className="knowledge-callout" key={index}>{callout.map((part, partIndex) => <p key={partIndex}>{inlineMarkdown(part.replace(/^\[!\w+\]\s*/, ""), onWikiLink)}</p>)}</aside>);
      continue;
    }
    if (/^-\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^-\s+/.test(lines[index])) { items.push(lines[index].replace(/^-\s+/, "")); index += 1; }
      blocks.push(<ul key={index}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item, onWikiLink)}</li>)}</ul>);
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+|^-\s+|^>\s?\[!/.test(lines[index])) { paragraph.push(lines[index]); index += 1; }
    blocks.push(<p key={index}>{inlineMarkdown(paragraph.join(" "), onWikiLink)}</p>);
  }
  return <>{blocks}</>;
}

function inlineMarkdown(text: string, onWikiLink: (label: string) => void): ReactNode[] {
  const parts = text.split(/(\[\[[^\]]+\]\]|`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("[[") && part.endsWith("]]")) {
      const value = part.slice(2, -2);
      return <button type="button" className="knowledge-wikilink" key={index} onClick={() => onWikiLink(value)}>{value.split("|").pop()}</button>;
    }
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}
