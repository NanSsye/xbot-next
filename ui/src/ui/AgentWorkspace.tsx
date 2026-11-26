import { ArrowDown, ArrowUp, Bot, ChevronLeft, FileText, MessageSquare, Plus, RefreshCw, Wrench } from "lucide-react";
import { type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AgentTask, AgentTaskDetail } from "../types";
import "./agent-workspace.css";

const PAGE_SIZE = 50;
const LEGACY_SOURCE = "terminal:control-ui";
const SESSION_KEY = "xbot.agent.workspace.source";
const PROMPTS = ["帮我梳理今天的工作计划", "把一段内容整理成一份清单"];
type Turn = AgentTask & { activity?: string[]; failed?: boolean };

function newSource() {
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) => n.toString(16).padStart(2, "0")).join("");
  return `terminal:control-ui:${id}`;
}

function mergeTurns(previous: Turn[], incoming: Turn[]) {
  const turns = new Map(previous.map((turn) => [turn.task_id, turn]));
  for (const turn of incoming) {
    const latest = turns.get(turn.task_id);
    if (turn.status === "running" && latest && latest.status !== "disconnected") continue;
    turns.set(turn.task_id, { ...latest, ...turn, failed: false });
  }
  return [...turns.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function AgentWorkspace({ renderText, onSettings }: {
  renderText: (text: string) => ReactNode;
  onSettings: () => void;
}) {
  const [llmStatus, setLlmStatus] = useState<Record<string, unknown> | null>(null);
  const [source, setSource] = useState(() => {
    const remembered = sessionStorage.getItem(SESSION_KEY) ?? "";
    return /^terminal:control-ui(:[a-f0-9]{32})?$/.test(remembered) ? remembered : newSource();
  });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busySource, setBusySource] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [hasOlder, setHasOlder] = useState(false);
  const [away, setAway] = useState(false);
  const [loadingSource, setLoadingSource] = useState("");
  const historyPage = useRef(new Map<string, number>());
  const inFlight = useRef(false);
  const feed = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const composerId = useId();
  const stickToEnd = useRef(true);
  const prependHeight = useRef<number | null>(null);
  const currentRef = useRef(source);
  const sessions = Array.from(new Map([...turns].reverse().map((turn) => [turn.source, turn])).values())
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const current = turns.filter((turn) => turn.source === source).reverse();
  const draft = drafts[source] ?? "";
  const busy = busySource !== "";
  const legacy = source === LEGACY_SOURCE;
  const model = typeof llmStatus?.model === "string" ? llmStatus.model : "Hermes Agent";
  const unavailable = llmStatus?.enabled === false || llmStatus?.has_api_key === false;
  const recovering = !legacy && busySource !== source && ["running", "disconnected"].includes(current.at(-1)?.status ?? "");

  function updateDraft(value: string, target = source) {
    setDrafts((previous) => ({ ...previous, [target]: value }));
  }

  async function loadHistory(target?: string, older = false) {
    const offset = target && older ? historyPage.current.get(target) ?? 0 : 0;
    if (target) setLoadingSource(target);
    try {
      const page = await api.agentChatHistory(target, offset);
      if (target && currentRef.current === target) {
        if (older) prependHeight.current = feed.current?.scrollHeight ?? null;
        historyPage.current.set(target, offset + page.length);
        setHasOlder(page.length === PAGE_SIZE);
      }
      setTurns((previous) => mergeTurns(previous, page));
    } catch (err) {
      setError(err instanceof Error ? err.message : "历史加载失败。");
    } finally {
      if (target) setLoadingSource((value) => value === target ? "" : value);
    }
  }

  useEffect(() => {
    let active = true;
    void api.llmStatus().then((status) => {
      if (active) setLlmStatus(status);
    }).catch((err: unknown) => {
      if (active) setError(err instanceof Error ? err.message : "无法读取模型状态。");
    });
    void loadHistory();
    if (sessionStorage.getItem(SESSION_KEY) === source) void loadHistory(source);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!recovering) return;
    let cancelled = false;
    let attempts = 0;
    let timer: number;
    async function poll() {
      try {
        const page = await api.agentChatHistory(source);
        if (!cancelled) setTurns((previous) => mergeTurns(previous, page));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "无法恢复任务状态。");
      } finally {
        if (!cancelled && ++attempts < 150) timer = window.setTimeout(poll, 2000);
      }
    }
    timer = window.setTimeout(poll, 2000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [source, recovering]);
  useLayoutEffect(() => {
    const pane = feed.current;
    if (!pane) return;
    if (prependHeight.current !== null) {
      pane.scrollTop += pane.scrollHeight - prependHeight.current;
      prependHeight.current = null;
    } else if (stickToEnd.current) {
      pane.scrollTop = pane.scrollHeight;
    }
  }, [turns, source]);

  function openSession(next: string, existing = true) {
    sessionStorage.setItem(SESSION_KEY, next);
    currentRef.current = next;
    stickToEnd.current = true;
    prependHeight.current = null;
    setAway(false);
    setHasOlder(false);
    setError("");
    setHistoryOpen(false);
    setSource(next);
    if (existing) void loadHistory(next);
    else composer.current?.focus();
  }

  async function send() {
    const text = draft.trim();
    if (!text || inFlight.current || unavailable || legacy) return;
    inFlight.current = true;
    sessionStorage.setItem(SESSION_KEY, source);
    setBusySource(source);
    setError("");
    setAway(false);
    stickToEnd.current = true;
    updateDraft("");
    let id = newSource();
    const pending: Turn = { task_id: id, source, input: text, output: "", status: "running", created_at: new Date().toISOString() };
    setTurns((previous) => mergeTurns(previous, [pending]));
    let accepted = false;
    function update(patch: (turn: Turn) => Turn) {
      setTurns((previous) => previous.map((turn) => turn.task_id === id ? patch(turn) : turn));
    }
    try {
      const result = await api.streamAgentChat(text, source, (frame) => {
        if (frame.type === "accepted") {
          accepted = true;
          const oldId = id;
          id = frame.task_id;
          setTurns((previous) => previous.map((turn) => turn.task_id === oldId ? { ...turn, task_id: frame.task_id } : turn));
        } else if (frame.type === "delta") {
          update((turn) => turn.status === "running" ? { ...turn, output: turn.output + frame.text } : turn);
        } else if (frame.type === "tool.started") {
          update((turn) => ({ ...turn, activity: [...(turn.activity ?? []), frame.tool] }));
        }
      });
      update((turn) => ({ ...turn, ...result, failed: false }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "发送失败。";
      if (accepted) update((turn) => ({ ...turn, status: "disconnected", failed: true }));
      else {
        setTurns((previous) => previous.filter((turn) => turn.task_id !== id));
        setDrafts((previous) => ({ ...previous, [source]: previous[source] || text }));
      }
      if (currentRef.current === source) setError(message);
    } finally {
      inFlight.current = false;
      setBusySource("");
    }
  }

  return (
    <section className={`agent-workspace${historyOpen ? " agent-workspace--history" : ""}`}>
      <aside className="agent-history" aria-label="会话历史">
        <button type="button" className="agent-new" onClick={() => openSession(newSource(), false)}><Plus size={17} /> 新对话</button>
        <div className="agent-history-label">
          <span>最近对话</span>
          <button type="button" className="icon-button" title="刷新历史" aria-label="刷新历史" onClick={() => { setError(""); void loadHistory(); void loadHistory(source); }}><RefreshCw size={14} /></button>
        </div>
        <ul role="list">{sessions.map((session) => (
          <li key={session.source}>
            <button type="button" title={session.input} aria-current={session.source === source ? "true" : undefined} onClick={() => openSession(session.source)}>
              <MessageSquare size={15} /><span>{session.source === LEGACY_SOURCE ? "旧控制台对话" : session.input || "Agent 对话"}</span>
            </button>
          </li>
        ))}</ul>
      </aside>
      <div className="agent-thread" role="region" aria-label="Agent 对话">
        <header className="agent-thread-head">
          <button type="button" className="icon-button agent-history-toggle" aria-label="切换会话列表" aria-expanded={historyOpen} onClick={() => setHistoryOpen(!historyOpen)}>
            {historyOpen ? <ChevronLeft size={18} /> : <MessageSquare size={18} />}
          </button>
          <h1>{legacy ? "旧控制台对话" : current[0]?.input || "新对话"}</h1>
          <span className="agent-model" title={model}><Bot size={15} />{model}</span>
        </header>
        <div className="agent-thread-feed" ref={feed} onScroll={(event) => {
          const node = event.currentTarget;
          stickToEnd.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
          setAway(!stickToEnd.current);
        }}>
          {hasOlder && <button type="button" className="ghost-button agent-older" disabled={loadingSource === source} onClick={() => void loadHistory(source, true)}>加载更早的消息</button>}
          {current.length === 0 && loadingSource !== source && <div className="agent-welcome"><Bot size={29} /><h2>今天想做什么？</h2>
            <div>{PROMPTS.map((prompt) => <button key={prompt} type="button" className="ghost-button" onClick={() => { updateDraft(prompt); composer.current?.focus(); }}>{prompt}</button>)}</div>
          </div>}
          {loadingSource === source && current.length === 0 && <p className="agent-progress">正在加载历史…</p>}
          <ol className="agent-messages" role="list" aria-label="对话消息">{current.map((turn) => <li key={turn.task_id}>
            <div className="agent-user">{turn.input}</div>
            <AgentTurnBody turn={turn} renderText={renderText} />
          </li>)}</ol>
        </div>
        <footer className="agent-thread-footer">
          {away && <button type="button" className="icon-button agent-jump" title="回到最新消息" aria-label="回到最新消息" onClick={() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight; }}><ArrowDown size={18} /></button>}
          {error && <p role="alert" className="agent-issue">{error}</p>}
          {unavailable && <p className="agent-issue">尚未配置模型。 <button type="button" className="ghost-button" onClick={onSettings}>打开设置</button></p>}
          <div className="agent-progress" role="status">{busySource === source ? "Agent 正在回复…" : ""}</div>
          {legacy ? <button type="button" className="ghost-button" onClick={() => openSession(newSource(), false)}><Plus size={16} /> 新对话</button> : <form className="agent-compose" onSubmit={(event) => { event.preventDefault(); void send(); }}>
            <label className="sr-only" htmlFor={composerId}>消息</label>
            <textarea id={composerId} ref={composer} maxLength={32000} value={draft} onChange={(event) => updateDraft(event.target.value)} placeholder="发消息给 Agent" onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }} />
            <button type="submit" aria-label="发送" title="发送" disabled={busy || unavailable || !draft.trim()}><ArrowUp size={20} /></button>
          </form>}
        </footer>
      </div>
    </section>
  );
}

function AgentTurnBody({ turn, renderText }: { turn: Turn; renderText: (text: string) => ReactNode }) {
  const [detail, setDetail] = useState<AgentTaskDetail | null>(null);
  const [issue, setIssue] = useState("");
  const tools = detail ? detail.timeline.filter((call) => call.type === "tool.started").map((call) => {
    const content = call.content as { tool?: string } | undefined;
    return content?.tool || "工具";
  }) : turn.activity;
  const finished = ["completed", "failed"].includes(turn.status);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded || !finished || detail) return;
    let active = true;
    setIssue("");
    void api.agentTaskDetail(turn.task_id).then((result) => {
      if (active) setDetail(result);
    }).catch((err: unknown) => {
      if (active) setIssue(err instanceof Error ? err.message : "无法加载执行过程。");
    });
    return () => { active = false; };
  }, [expanded, finished, detail, turn.task_id]);
  return <div className="agent-answer">
    <span className="agent-answer-label"><Bot size={17} /> Agent</span>
    {(tools?.length || finished) ? <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary><Wrench size={14} /> 执行过程{tools?.length ? ` · ${tools.length}` : ""}</summary>
      {issue ? <p role="alert">{issue}</p> : tools ? (
        tools.length ? <ul>{tools.map((tool, i) => <li key={`${tool}-${i}`}>{tool}</li>)}</ul> : <p>本轮没有工具调用。</p>
      ) : <p>{finished ? "正在加载…" : "正在执行…"}</p>}
      {detail?.artifacts.map((artifact) => <article className="hermes-inline-artifact" key={artifact.id}>
        <FileText size={15} /><div><strong>{artifact.kind}</strong><p>{artifact.summary || artifact.path}</p></div>
      </article>)}
    </details> : null}
    {turn.output ? <div className={turn.status === "failed" ? "agent-issue" : "markdown-body"}>{renderText(turn.output)}</div> : <p className="agent-progress">{turn.status === "running" ? "等待回复…" : "没有收到回复。"}</p>}
    {turn.failed && <p className="agent-issue">{turn.status === "disconnected" ? "连接已中断，刷新历史可查看任务结果。" : "本轮执行失败。"}</p>}
  </div>;
}
