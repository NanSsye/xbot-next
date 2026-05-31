import {
  Activity,
  Bot,
  CalendarClock,
  CheckCircle2,
  Circle,
  Clock3,
  KeyRound,
  LogIn,
  Monitor,
  MessagesSquare,
  Moon,
  Network,
  Package,
  Pause,
  Play,
  QrCode,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Settings,
  Sun,
  Trash2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiBase, clearApiToken, getApiToken, setApiToken, wsUrl } from "../api";
import type {
  AdapterInfo,
  AdapterStatus,
  AgentEvent,
  AgentMemoryInfo,
  AgentToolInfo,
  BackgroundTask,
  Conversation,
  IlinkQrCode,
  Message,
  PluginInfo,
  ScheduledJob,
  SkillInfo,
  SystemStatus,
  UiEvent,
} from "../types";

type View = "chat" | "overview" | "agent" | "channels" | "extensions" | "background" | "schedules" | "logs" | "settings";
type DeliveryMode = "console" | "channel";
type ThemeMode = "system" | "light" | "dark";
type ConsoleMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

const navItems: Array<{ id: View; label: string; icon: typeof MessagesSquare }> = [
  { id: "chat", label: "对话", icon: MessagesSquare },
  { id: "overview", label: "总览", icon: Activity },
  { id: "agent", label: "Agent", icon: Bot },
  { id: "channels", label: "通道", icon: Network },
  { id: "extensions", label: "扩展", icon: Package },
  { id: "background", label: "后台任务", icon: Clock3 },
  { id: "schedules", label: "定时任务", icon: CalendarClock },
  { id: "logs", label: "活动流", icon: Bot },
  { id: "settings", label: "设置", icon: Settings },
];

const THEME_STORAGE_KEY = "xbot.control.theme";

function readThemeMode(): ThemeMode {
  const value = window.localStorage.getItem(THEME_STORAGE_KEY);
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function App() {
  const [view, setView] = useState<View>("chat");
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  const [adapterStatuses, setAdapterStatuses] = useState<Record<string, AdapterStatus>>({});
  const [ilinkQr, setIlinkQr] = useState<IlinkQrCode | null>(null);
  const [wechat869Qr, setWechat869Qr] = useState<AdapterStatus | null>(null);
  const [channelBusy, setChannelBusy] = useState("");
  const [channelMessage, setChannelMessage] = useState("");
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [consoleMessagesByContext, setConsoleMessagesByContext] = useState<Record<string, ConsoleMessage[]>>({});
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [tools, setTools] = useState<AgentToolInfo[]>([]);
  const [llmStatus, setLlmStatus] = useState<Record<string, unknown> | null>(null);
  const [mcpStatus, setMcpStatus] = useState<Record<string, unknown> | null>(null);
  const [memories, setMemories] = useState<AgentMemoryInfo[]>([]);
  const [liveEvents, setLiveEvents] = useState<UiEvent[]>([]);
  const [backgroundTasks, setBackgroundTasks] = useState<BackgroundTask[]>([]);
  const [scheduledJobs, setScheduledJobs] = useState<ScheduledJob[]>([]);
  const [query, setQuery] = useState("");
  const [input, setInput] = useState("");
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>("console");
  const [toolQuery, setToolQuery] = useState("");
  const [memoryKind, setMemoryKind] = useState("semantic");
  const [memorySummary, setMemorySummary] = useState("");
  const [scheduleName, setScheduleName] = useState("");
  const [scheduleExpr, setScheduleExpr] = useState("");
  const [scheduleInput, setScheduleInput] = useState("");
  const [scheduleTimezone, setScheduleTimezone] = useState("Asia/Shanghai");
  const [scheduleMaxRuns, setScheduleMaxRuns] = useState("");
  const [apiToken, setApiTokenState] = useState(getApiToken());
  const [themeMode, setThemeMode] = useState<ThemeMode>(readThemeMode);
  const [wsRevision, setWsRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selectedConversation = conversations.find((item) => item.id === selectedConversationId);
  const consoleContextKey = selectedConversationId || "control-ui";
  const consoleMessages = consoleMessagesByContext[consoleContextKey] ?? [];
  const filteredConversations = useMemo(() => {
    const text = query.trim().toLowerCase();
    if (!text) return conversations;
    return conversations.filter((item) =>
      [item.id, item.title, item.platform, item.adapter, item.scope, item.raw_id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(text)),
    );
  }, [conversations, query]);

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const [
        nextStatus,
        nextAdapters,
        nextPlugins,
        nextSkills,
        nextConversations,
        nextEvents,
        nextTools,
        nextLlmStatus,
        nextMcpStatus,
        nextMemories,
        nextBackground,
        nextSchedules,
      ] =
        await Promise.all([
          api.status(),
          api.adapters(),
          api.plugins(),
          api.skills(),
          api.conversations(),
          api.agentEvents(80),
          api.tools(),
          api.llmStatus(),
          api.mcpStatus(),
          api.memories(50),
          api.backgroundTasks(50),
          api.scheduledJobs(100),
        ]);
      setStatus(nextStatus);
      setAdapters(nextAdapters);
      setPlugins(nextPlugins);
      setSkills(nextSkills);
      setConversations(nextConversations);
      setEvents(nextEvents);
      setTools(nextTools);
      setLlmStatus(nextLlmStatus);
      setMcpStatus(nextMcpStatus);
      setMemories(nextMemories);
      setBackgroundTasks(nextBackground);
      setScheduledJobs(nextSchedules);
      if (!selectedConversationId && nextConversations.length > 0) {
        setSelectedConversationId(nextConversations[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [selectedConversationId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const resolved = themeMode === "system" ? (media.matches ? "dark" : "light") : themeMode;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.colorScheme = resolved;
      window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    };
    applyTheme();
    if (themeMode !== "system") return;
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [themeMode]);

  useEffect(() => {
    if (view !== "channels" || adapters.length === 0) return;
    void Promise.all(adapters.map((adapter) => refreshAdapterStatus(adapter.name)));
  }, [view, adapters]);

  useEffect(() => {
    if (!selectedConversationId) {
      setMessages([]);
      return;
    }
    api
      .messages(selectedConversationId, 100)
      .then(setMessages)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedConversationId]);

  useEffect(() => {
    const socket = new WebSocket(wsUrl());
    socket.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data) as UiEvent;
        setLiveEvents((current) => [item, ...current].slice(0, 100));
      } catch {
        // Ignore malformed event frames.
      }
    };
    socket.onerror = () => {
      setLiveEvents((current) => [
        {
          id: crypto.randomUUID(),
          type: "ui.websocket_error",
          topic: "ui",
          data: {},
          created_at: new Date().toISOString(),
        },
        ...current,
      ]);
    };
    return () => socket.close();
  }, [wsRevision]);

  const requiresToken = error.toLowerCase().includes("unauthorized");

  async function sendMessage() {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");
    setError("");
    const contextKey = selectedConversationId || "control-ui";
    const userMessage: ConsoleMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setConsoleMessagesByContext((current) => ({
      ...current,
      [contextKey]: [...(current[contextKey] ?? []), userMessage],
    }));
    const contextBlock = selectedConversation
      ? [
          "Control UI console message.",
          "Use the selected channel conversation only as context.",
          "Do not send anything to the original channel unless explicitly instructed and tool policy allows it.",
          `delivery_mode: ${deliveryMode}`,
          `context_conversation_id: ${selectedConversation.id}`,
          `context_platform: ${selectedConversation.platform}`,
          `context_adapter: ${selectedConversation.adapter}`,
          `context_scope: ${selectedConversation.scope}`,
          "recent_messages:",
          ...messages.slice(-20).map((message) => {
            const content = (message.content ?? "").replace(/\s+/g, " ").slice(0, 500);
            return `- ${message.sender_name || message.sender_id}: ${content}`;
          }),
          `content: ${text}`,
        ].join("\n")
      : text;
    try {
      const result = await api.sendAgentTask(contextBlock, "terminal:control-ui");
      const assistantMessage: ConsoleMessage = {
        id: result.task_id,
        role: "assistant",
        content: result.output || "Agent 没有返回文本结果，请查看右侧活动流。",
        created_at: result.created_at,
      };
      setConsoleMessagesByContext((current) => ({
        ...current,
        [contextKey]: [...(current[contextKey] ?? []), assistantMessage],
      }));
      setEvents((current) => [
        {
          task_id: result.task_id,
          type: "task.completed",
          content: result.output,
          created_at: result.created_at,
        },
        ...current,
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      void loadAll();
    }
  }

  async function deleteConversation(id: string) {
    if (!window.confirm("只删除本地会话记录，不影响原通道。继续？")) return;
    await api.deleteConversation(id);
    setSelectedConversationId("");
    await loadAll();
  }

  async function toggleAdapter(name: string, enabled: boolean) {
    setError("");
    try {
      const next = enabled ? await api.disableAdapter(name) : await api.enableAdapter(name);
      setAdapters(next);
      await refreshAdapterStatus(name);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshAdapterStatus(name: string) {
    try {
      const next = await api.adapterStatus(name);
      setAdapterStatuses((current) => ({ ...current, [name]: next }));
    } catch (err) {
      setAdapterStatuses((current) => ({
        ...current,
        [name]: {
          adapter: name,
          error: err instanceof Error ? err.message : String(err),
        },
      }));
    }
  }

  async function startIlinkLogin() {
    setChannelBusy("wechat_ilink");
    setChannelMessage("");
    setError("");
    try {
      const nextQr = await api.wechatIlinkQrcode();
      setIlinkQr(nextQr);
      setChannelMessage("iLink 登录二维码已生成，请用微信扫码。");
      await refreshAdapterStatus("wechat_ilink");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChannelBusy("");
    }
  }

  async function pollIlinkLogin() {
    setChannelBusy("wechat_ilink");
    setChannelMessage("");
    setError("");
    try {
      const next = await api.wechatIlinkLoginStatus(ilinkQr?.qrcode);
      setAdapterStatuses((current) => ({ ...current, wechat_ilink: next }));
      setChannelMessage(next.logged_in ? "iLink 已登录。" : "尚未确认登录，请扫码后再检查。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChannelBusy("");
    }
  }

  async function startWechat869Login() {
    setChannelBusy("wechat869");
    setChannelMessage("");
    setError("");
    try {
      const next = await api.wechat869LoginStart();
      setAdapterStatuses((current) => ({ ...current, wechat869: next }));
      if (next.qr_url || next.qr_image_url || next.qrcode || next.uuid) {
        setWechat869Qr(next);
      }
      setChannelMessage(String(next.message ?? "869 登录流程待接入，当前仅显示配置与运行状态。"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChannelBusy("");
    }
  }

  async function pollWechat869Login() {
    setChannelBusy("wechat869");
    setChannelMessage("");
    setError("");
    try {
      const next = await api.wechat869LoginStatus();
      setAdapterStatuses((current) => ({ ...current, wechat869: next }));
      if (next.logged_in) {
        setWechat869Qr(null);
      }
      setChannelMessage(next.logged_in ? "869 已登录。" : "尚未确认登录，请扫码后再检查。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChannelBusy("");
    }
  }

  async function togglePlugin(name: string, enabled: boolean) {
    setError("");
    try {
      if (enabled) {
        await api.disablePlugin(name);
      } else {
        await api.enablePlugin(name);
      }
      setPlugins(await api.plugins());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function toggleSkill(name: string, enabled: boolean) {
    setError("");
    try {
      if (enabled) {
        await api.disableSkill(name);
      } else {
        await api.enableSkill(name);
      }
      setSkills(await api.skills());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function cancelBackgroundTask(taskId: string) {
    setError("");
    try {
      await api.cancelBackgroundTask(taskId);
      setBackgroundTasks(await api.backgroundTasks(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function replayBackgroundTask(taskId: string) {
    setError("");
    try {
      await api.replayBackgroundTask(taskId);
      setBackgroundTasks(await api.backgroundTasks(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function updateScheduledJob(action: "pause" | "resume" | "run" | "delete", jobId: string) {
    setError("");
    try {
      if (action === "pause") await api.pauseScheduledJob(jobId);
      if (action === "resume") await api.resumeScheduledJob(jobId);
      if (action === "run") await api.runScheduledJob(jobId);
      if (action === "delete") {
        if (!window.confirm("删除该定时任务？")) return;
        await api.deleteScheduledJob(jobId);
      }
      setScheduledJobs(await api.scheduledJobs(100));
      setBackgroundTasks(await api.backgroundTasks(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function createScheduledJob() {
    const inputText = scheduleInput.trim();
    const schedule = scheduleExpr.trim();
    if (!inputText || !schedule) return;
    setError("");
    try {
      await api.createScheduledJob({
        input: inputText,
        schedule,
        name: scheduleName.trim() || undefined,
        timezone: scheduleTimezone.trim() || "Asia/Shanghai",
        source: "control-ui:schedule",
        reply_policy: "none",
        max_runs: scheduleMaxRuns.trim() ? Number(scheduleMaxRuns) : null,
      });
      setScheduleName("");
      setScheduleExpr("");
      setScheduleInput("");
      setScheduleMaxRuns("");
      setScheduledJobs(await api.scheduledJobs(100));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function reloadMcp() {
    setError("");
    try {
      setMcpStatus(await api.reloadMcp());
      setTools(await api.tools());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function createMemory() {
    const summary = memorySummary.trim();
    if (!summary) return;
    setError("");
    try {
      await api.createMemory(memoryKind, summary);
      setMemorySummary("");
      setMemories(await api.memories(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function deleteMemory(memoryId: string) {
    if (!window.confirm("删除这条记忆？")) return;
    setError("");
    try {
      await api.deleteMemory(memoryId);
      setMemories(await api.memories(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function compactMemories() {
    setError("");
    try {
      await api.compactMemories();
      setMemories(await api.memories(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark">x</div>
          <div>
            <div className="brand__name">xbot</div>
            <div className="brand__sub">Control UI</div>
          </div>
        </div>
        <nav className="nav">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`nav__item ${view === item.id ? "nav__item--active" : ""}`}
                onClick={() => setView(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <header className="topbar">
        <div className="topbar__title">
          <span>{navItems.find((item) => item.id === view)?.label}</span>
          <small>{selectedConversation ? selectedConversation.id : "xbot backend"}</small>
        </div>
        <div className="topbar__actions">
          <StatusPill label={status?.engine.state ?? "unknown"} tone={status?.engine.state === "running" ? "ok" : "warn"} />
          <StatusPill label={`${adapters.length} adapters`} tone="neutral" />
          <ThemeToggle value={themeMode} onChange={setThemeMode} />
          <button className="icon-button" onClick={() => void loadAll()} title="刷新">
            <RefreshCw size={16} />
          </button>
        </div>
      </header>

      <main className="content">
        {error ? <div className="error-banner">{error}</div> : null}
        {requiresToken ? (
          <AuthGate
            token={apiToken}
            setToken={setApiTokenState}
            onSave={() => {
              setApiToken(apiToken);
              setWsRevision((value) => value + 1);
              void loadAll();
            }}
            onClear={() => {
              clearApiToken();
              setApiTokenState("");
            }}
          />
        ) : null}
        {view === "chat" && (
          <ChatView
            conversations={filteredConversations}
            query={query}
            setQuery={setQuery}
            selectedConversationId={selectedConversationId}
            setSelectedConversationId={setSelectedConversationId}
            deleteConversation={deleteConversation}
            messages={messages}
            consoleMessages={consoleMessages}
            input={input}
            setInput={setInput}
            sendMessage={sendMessage}
            busy={busy}
            deliveryMode={deliveryMode}
            setDeliveryMode={setDeliveryMode}
            events={events}
            liveEvents={liveEvents}
          />
        )}
        {view === "overview" && <Overview status={status} adapters={adapters} jobs={scheduledJobs} tasks={backgroundTasks} />}
        {view === "agent" && (
          <AgentView
            tools={tools}
            llmStatus={llmStatus}
            mcpStatus={mcpStatus}
            memories={memories}
            toolQuery={toolQuery}
            setToolQuery={setToolQuery}
            memoryKind={memoryKind}
            setMemoryKind={setMemoryKind}
            memorySummary={memorySummary}
            setMemorySummary={setMemorySummary}
            reloadMcp={reloadMcp}
            createMemory={createMemory}
            deleteMemory={deleteMemory}
            compactMemories={compactMemories}
            refresh={loadAll}
          />
        )}
        {view === "channels" && (
          <Channels
            adapters={adapters}
            adapterStatuses={adapterStatuses}
            ilinkQr={ilinkQr}
            wechat869Qr={wechat869Qr}
            channelBusy={channelBusy}
            channelMessage={channelMessage}
            toggleAdapter={toggleAdapter}
            refreshAdapterStatus={refreshAdapterStatus}
            startIlinkLogin={startIlinkLogin}
            pollIlinkLogin={pollIlinkLogin}
            startWechat869Login={startWechat869Login}
            pollWechat869Login={pollWechat869Login}
          />
        )}
        {view === "extensions" && (
          <Extensions
            plugins={plugins}
            skills={skills}
            togglePlugin={togglePlugin}
            toggleSkill={toggleSkill}
            reloadPlugins={async () => setPlugins(await api.reloadPlugins())}
            reloadSkills={async () => setSkills(await api.reloadSkills())}
          />
        )}
        {view === "background" && (
          <BackgroundTasks
            tasks={backgroundTasks}
            replayTask={replayBackgroundTask}
            cancelTask={cancelBackgroundTask}
            refresh={async () => setBackgroundTasks(await api.backgroundTasks(50))}
          />
        )}
        {view === "schedules" && (
          <Schedules
            jobs={scheduledJobs}
            name={scheduleName}
            setName={setScheduleName}
            schedule={scheduleExpr}
            setSchedule={setScheduleExpr}
            input={scheduleInput}
            setInput={setScheduleInput}
            timezone={scheduleTimezone}
            setTimezone={setScheduleTimezone}
            maxRuns={scheduleMaxRuns}
            setMaxRuns={setScheduleMaxRuns}
            createJob={createScheduledJob}
            updateJob={updateScheduledJob}
            refresh={async () => setScheduledJobs(await api.scheduledJobs(100))}
          />
        )}
        {view === "logs" && <ActivityPanel events={events} liveEvents={liveEvents} />}
        {view === "settings" && (
          <SettingsView
            token={apiToken}
            setToken={setApiTokenState}
            themeMode={themeMode}
            setThemeMode={setThemeMode}
            saveToken={() => {
              setApiToken(apiToken);
              setWsRevision((value) => value + 1);
              void loadAll();
            }}
            clearToken={() => {
              clearApiToken();
              setApiTokenState("");
              setWsRevision((value) => value + 1);
            }}
          />
        )}
      </main>
    </div>
  );
}

function ThemeToggle({ value, onChange }: { value: ThemeMode; onChange: (value: ThemeMode) => void }) {
  const next = value === "system" ? "light" : value === "light" ? "dark" : "system";
  const Icon = value === "system" ? Monitor : value === "light" ? Sun : Moon;
  const label = value === "system" ? "跟随系统" : value === "light" ? "日间模式" : "夜间模式";
  return (
    <button className="icon-button" onClick={() => onChange(next)} title={`主题：${label}`}>
      <Icon size={16} />
    </button>
  );
}

function AuthGate({
  token,
  setToken,
  onSave,
  onClear,
}: {
  token: string;
  setToken: (value: string) => void;
  onSave: () => void;
  onClear: () => void;
}) {
  return (
    <section className="auth-gate panel">
      <div>
        <div className="auth-gate__title">需要 API Token</div>
        <p>当前后端已开启控制台认证。Token 只保存在本浏览器 localStorage，用于访问 REST API 和 WebSocket 事件流。</p>
      </div>
      <div className="auth-gate__form">
        <input
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="粘贴 XBOT_API_TOKEN"
          type="password"
          autoComplete="current-password"
        />
        <button className="primary-button" disabled={!token.trim()} onClick={onSave}>
          保存并重试
        </button>
        <button className="ghost-button" onClick={onClear}>
          清除
        </button>
      </div>
    </section>
  );
}

function ChatView(props: {
  conversations: Conversation[];
  query: string;
  setQuery: (value: string) => void;
  selectedConversationId: string;
  setSelectedConversationId: (value: string) => void;
  deleteConversation: (id: string) => void;
  messages: Message[];
  consoleMessages: ConsoleMessage[];
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => void;
  busy: boolean;
  deliveryMode: DeliveryMode;
  setDeliveryMode: (value: DeliveryMode) => void;
  events: AgentEvent[];
  liveEvents: UiEvent[];
}) {
  return (
    <section className="chat-grid">
      <div className="panel conversation-list">
        <div className="search">
          <Search size={15} />
          <input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="搜索会话" />
        </div>
        <div className="conversation-scroll">
          {props.conversations.map((item) => (
            <button
              key={item.id}
              className={`conversation-item ${props.selectedConversationId === item.id ? "conversation-item--active" : ""}`}
              onClick={() => props.setSelectedConversationId(item.id)}
            >
              <span className="conversation-item__title">{item.title || item.raw_id}</span>
              <span className="conversation-item__meta">
                {item.platform} / {item.adapter} / {item.scope}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel chat-panel">
        <div className="chat-panel__toolbar">
          <Segmented
            value={props.deliveryMode}
            onChange={props.setDeliveryMode}
            options={[
              ["console", "控制台"],
              ["channel", "回发通道"],
            ]}
          />
          {props.selectedConversationId ? (
            <button className="ghost-button danger" onClick={() => props.deleteConversation(props.selectedConversationId)}>
              <Trash2 size={15} />
              删除本地记录
            </button>
          ) : null}
        </div>
        <div className="message-list">
          {props.messages.length === 0 && props.consoleMessages.length === 0 ? (
            <EmptyState title="暂无历史消息" text="选择通道会话后，这里会展示最近消息。页面内聊天默认不回发通道。" />
          ) : (
            <>
              {props.messages.map((message) => <MessageBubble key={`${message.id}-${message.timestamp}`} message={message} />)}
              {props.consoleMessages.length > 0 ? <div className="message-separator">控制台对话</div> : null}
              {props.consoleMessages.map((message) => <ConsoleMessageBubble key={message.id} message={message} />)}
            </>
          )}
        </div>
        <div className="composer">
          <textarea
            value={props.input}
            onChange={(event) => props.setInput(event.target.value)}
            placeholder="在控制台向 Agent 提问。默认只在页面显示，不回发原通道。"
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                void props.sendMessage();
              }
            }}
          />
          <button className="primary-button" disabled={props.busy || !props.input.trim()} onClick={() => void props.sendMessage()}>
            <Send size={16} />
            {props.busy ? "发送中" : "发送"}
          </button>
        </div>
      </div>

      <ActivityPanel events={props.events} liveEvents={props.liveEvents} compact />
    </section>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isAgent = message.sender_id.includes("agent") || message.raw?.direction === "reply";
  return (
    <article className={`message ${isAgent ? "message--agent" : ""}`}>
      <div className="message__meta">
        <span>{message.sender_name || message.sender_id}</span>
        <span>{formatDate(message.timestamp)}</span>
      </div>
      <div className="message__body">{message.content || `[${message.type}]`}</div>
    </article>
  );
}

function ConsoleMessageBubble({ message }: { message: ConsoleMessage }) {
  return (
    <article className={`message ${message.role === "assistant" ? "message--agent" : "message--user"}`}>
      <div className="message__meta">
        <span>{message.role === "assistant" ? "Agent" : "你"}</span>
        <span>{formatDate(message.created_at)}</span>
      </div>
      <div className="message__body">{message.content}</div>
    </article>
  );
}

function ActivityPanel({ events, liveEvents, compact = false }: { events: AgentEvent[]; liveEvents: UiEvent[]; compact?: boolean }) {
  const normalized = [
    ...liveEvents.map((event) => ({
      id: event.id,
      type: event.type,
      subtitle: event.topic,
      content: event.data,
      created_at: event.created_at,
    })),
    ...events.map((event, index) => ({
      id: `${event.task_id}-${event.type}-${index}`,
      type: event.type,
      subtitle: event.task_id,
      content: event.content,
      created_at: event.created_at,
    })),
  ].slice(0, compact ? 40 : 120);
  return (
    <aside className={`panel activity-panel ${compact ? "activity-panel--compact" : ""}`}>
      <div className="panel-title">活动流</div>
      <div className="activity-scroll">
        {normalized.length === 0 ? (
          <EmptyState title="暂无活动" text="Agent 工具调用、后台任务和 WebSocket 实时事件会显示在这里。" />
        ) : (
          normalized.map((event) => (
            <details key={event.id} className="activity-item">
              <summary>
                <span>{event.type}</span>
                <small>{formatDate(event.created_at)}</small>
              </summary>
              <div className="activity-item__topic">{event.subtitle}</div>
              <pre>{stringify(event.content)}</pre>
            </details>
          ))
        )}
      </div>
    </aside>
  );
}

function Overview({ status, adapters, jobs, tasks }: { status: SystemStatus | null; adapters: AdapterInfo[]; jobs: ScheduledJob[]; tasks: BackgroundTask[] }) {
  return (
    <section className="dashboard-grid">
      <Metric label="运行状态" value={status?.engine.state ?? "unknown"} />
      <Metric label="通道" value={String(adapters.length)} />
      <Metric label="定时任务" value={String(jobs.length)} />
      <Metric label="后台任务" value={String(tasks.length)} />
      <div className="panel wide">
        <div className="panel-title">系统</div>
        <pre className="code-block">{stringify(status)}</pre>
      </div>
    </section>
  );
}

function AgentView({
  tools,
  llmStatus,
  mcpStatus,
  memories,
  toolQuery,
  setToolQuery,
  memoryKind,
  setMemoryKind,
  memorySummary,
  setMemorySummary,
  reloadMcp,
  createMemory,
  deleteMemory,
  compactMemories,
  refresh,
}: {
  tools: AgentToolInfo[];
  llmStatus: Record<string, unknown> | null;
  mcpStatus: Record<string, unknown> | null;
  memories: AgentMemoryInfo[];
  toolQuery: string;
  setToolQuery: (value: string) => void;
  memoryKind: string;
  setMemoryKind: (value: string) => void;
  memorySummary: string;
  setMemorySummary: (value: string) => void;
  reloadMcp: () => Promise<void>;
  createMemory: () => Promise<void>;
  deleteMemory: (memoryId: string) => void;
  compactMemories: () => Promise<void>;
  refresh: () => Promise<void>;
}) {
  const query = toolQuery.trim().toLowerCase();
  const filteredTools = query
    ? tools.filter((item) =>
        [item.name, item.description, item.toolset, item.source, item.risk_level]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query)),
      )
    : tools;

  return (
    <section className="agent-grid">
      <div className="panel agent-status-panel">
        <div className="panel-title panel-title--with-action">
          <span>运行状态</span>
          <button className="ghost-button" onClick={() => void refresh()}>
            <RefreshCw size={14} />
            刷新
          </button>
        </div>
        <div className="status-grid">
          <StatusBlock title="LLM" data={llmStatus} />
          <StatusBlock title="MCP" data={mcpStatus} actionLabel="重载 MCP" action={reloadMcp} />
        </div>
      </div>

      <div className="panel tools-panel">
        <div className="panel-title panel-title--with-action">
          <div>
            <span>工具</span>
            <small>{filteredTools.length} / {tools.length}</small>
          </div>
          <div className="compact-search">
            <Search size={14} />
            <input value={toolQuery} onChange={(event) => setToolQuery(event.target.value)} placeholder="搜索工具" />
          </div>
        </div>
        <div className="tool-list">
          {filteredTools.length === 0 ? (
            <EmptyState title="没有匹配工具" text="换一个关键词，或检查 Agent toolset 配置。" />
          ) : (
            filteredTools.map((tool) => (
              <article key={tool.name} className="tool-item">
                <div className="tool-item__head">
                  <span>{tool.name}</span>
                  <StatusPill label={tool.risk_level} tone={tool.risk_level === "read" ? "ok" : tool.risk_level === "write" ? "warn" : "neutral"} />
                </div>
                <p>{tool.description || "无描述"}</p>
                <div className="tool-item__meta">
                  <span>{tool.toolset || "core"}</span>
                  <span>{tool.source || "builtin"}</span>
                  {tool.cacheable ? <span>cacheable</span> : null}
                </div>
              </article>
            ))
          )}
        </div>
      </div>

      <div className="panel memories-panel">
        <div className="panel-title panel-title--with-action">
          <span>长期记忆</span>
          <button className="ghost-button" onClick={() => void compactMemories()}>
            <RotateCcw size={14} />
            压缩
          </button>
        </div>
        <div className="memory-editor">
          <select value={memoryKind} onChange={(event) => setMemoryKind(event.target.value)}>
            <option value="semantic">semantic</option>
            <option value="user">user</option>
            <option value="project">project</option>
          </select>
          <textarea
            value={memorySummary}
            onChange={(event) => setMemorySummary(event.target.value)}
            placeholder="写入一条稳定、长期有用的记忆。不要保存密钥、临时日志或一次性任务进度。"
          />
          <button className="primary-button" disabled={!memorySummary.trim()} onClick={() => void createMemory()}>
            添加记忆
          </button>
        </div>
        <div className="memory-list">
          {memories.length === 0 ? (
            <EmptyState title="暂无记忆" text="Agent 写入或页面手动添加的长期记忆会显示在这里。" />
          ) : (
            memories.map((memory) => (
              <article key={memory.id} className="memory-item">
                <div>
                  <div className="memory-item__meta">
                    <span>{memory.kind}</span>
                    <span>{formatDate(memory.created_at)}</span>
                  </div>
                  <p>{memory.summary}</p>
                </div>
                <button className="icon-button danger" title="删除" onClick={() => deleteMemory(memory.id)}>
                  <Trash2 size={14} />
                </button>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function StatusBlock({
  title,
  data,
  actionLabel,
  action,
}: {
  title: string;
  data: Record<string, unknown> | null;
  actionLabel?: string;
  action?: () => Promise<void>;
}) {
  return (
    <div className="status-block">
      <div className="status-block__head">
        <span>{title}</span>
        {action && actionLabel ? (
          <button className="ghost-button" onClick={() => void action()}>
            {actionLabel}
          </button>
        ) : null}
      </div>
      <pre>{stringify(data ?? {})}</pre>
    </div>
  );
}

function Channels({
  adapters,
  adapterStatuses,
  ilinkQr,
  wechat869Qr,
  channelBusy,
  channelMessage,
  toggleAdapter,
  refreshAdapterStatus,
  startIlinkLogin,
  pollIlinkLogin,
  startWechat869Login,
  pollWechat869Login,
}: {
  adapters: AdapterInfo[];
  adapterStatuses: Record<string, AdapterStatus>;
  ilinkQr: IlinkQrCode | null;
  wechat869Qr: AdapterStatus | null;
  channelBusy: string;
  channelMessage: string;
  toggleAdapter: (name: string, enabled: boolean) => void;
  refreshAdapterStatus: (name: string) => Promise<void>;
  startIlinkLogin: () => Promise<void>;
  pollIlinkLogin: () => Promise<void>;
  startWechat869Login: () => Promise<void>;
  pollWechat869Login: () => Promise<void>;
}) {
  return (
    <section className="channels-grid">
      <div className="panel channel-panel">
        <div className="panel-title panel-title--with-action">
          <div>
            <span>通道</span>
            <small>页面开关会写入数据库，重启后继续生效；登录密钥仍由后端安全保存。</small>
          </div>
        </div>
        <div className="channel-card-grid">
          {adapters.map((item) => {
            const status = adapterStatuses[item.name] ?? {};
            const isIlink = item.name === "wechat_ilink";
            const is869 = item.name === "wechat869";
            return (
              <article key={item.name} className="channel-card">
                <div className="channel-card__head">
                  <div className="channel-card__title">
                    <Network size={18} />
                    <div>
                      <span>{channelDisplayName(item.name)}</span>
                      <small>{item.name} · {item.platform}</small>
                    </div>
                  </div>
                  <StatusPill label={item.status || "unknown"} tone={item.started ? "ok" : item.enabled ? "warn" : "neutral"} />
                </div>

                <div className="channel-card__actions">
                  <button className="ghost-button" onClick={() => toggleAdapter(item.name, item.enabled)}>
                    {item.enabled ? "停用通道" : "启用通道"}
                  </button>
                  <button className="icon-button" title="刷新状态" onClick={() => void refreshAdapterStatus(item.name)}>
                    <RefreshCw size={14} />
                  </button>
                  {isIlink ? (
                    <>
                      <button className="primary-button" disabled={channelBusy === item.name} onClick={() => void startIlinkLogin()}>
                        <QrCode size={15} />
                        获取二维码
                      </button>
                      <button className="ghost-button" disabled={channelBusy === item.name} onClick={() => void pollIlinkLogin()}>
                        <LogIn size={15} />
                        检查登录
                      </button>
                    </>
                  ) : null}
                  {is869 ? (
                    <>
                      <button className="primary-button" disabled={channelBusy === item.name} onClick={() => void startWechat869Login()}>
                        <QrCode size={15} />
                        获取二维码
                      </button>
                      <button className="ghost-button" disabled={channelBusy === item.name} onClick={() => void pollWechat869Login()}>
                        <LogIn size={15} />
                        检查登录
                      </button>
                    </>
                  ) : null}
                </div>

                <div className="channel-card__details">
                  <KeyValue label="配置启用" value={item.configured_enabled ? "是" : "否"} />
                  <KeyValue label="页面覆盖" value={item.persistent_enabled === undefined || item.persistent_enabled === null ? "默认" : item.persistent_enabled ? "启用" : "停用"} />
                  <KeyValue label="实际启用" value={item.enabled ? "是" : "否"} />
                  <KeyValue label="运行中" value={item.started ? "是" : "否"} />
                </div>

                {isIlink && ilinkQr ? (
                  <div className="qr-box">
                    {isImageUrl(ilinkQr.qr_url) ? <img src={ilinkQr.qr_url} alt="iLink 登录二维码" /> : <pre>{ilinkQr.qrcode}</pre>}
                    <small>扫码后点击“检查登录”。</small>
                  </div>
                ) : null}

                {is869 && wechat869Qr ? (
                  <div className="qr-box">
                    {isImageUrl(formatStatusValue(wechat869Qr.qr_image_url)) ? (
                      <img src={formatStatusValue(wechat869Qr.qr_image_url)} alt="869 登录二维码" />
                    ) : (
                      <pre>{formatStatusValue(wechat869Qr.qr_url || wechat869Qr.qrcode || wechat869Qr.uuid)}</pre>
                    )}
                    <small>{formatStatusValue(wechat869Qr.qr_url || wechat869Qr.qrcode || wechat869Qr.uuid)}</small>
                  </div>
                ) : null}

                <div className="channel-keys">
                  {channelStatusEntries(item.name, status).map(([label, value]) => (
                    <KeyValue key={label} label={label} value={formatStatusValue(value)} />
                  ))}
                </div>

                {status.error ? <div className="channel-card__error">{formatStatusValue(status.error)}</div> : null}
              </article>
            );
          })}
        </div>
        {channelMessage ? <div className="channel-message">{channelMessage}</div> : null}
      </div>
    </section>
  );
}

function Extensions({
  plugins,
  skills,
  togglePlugin,
  toggleSkill,
  reloadPlugins,
  reloadSkills,
}: {
  plugins: PluginInfo[];
  skills: SkillInfo[];
  togglePlugin: (name: string, enabled: boolean) => void;
  toggleSkill: (name: string, enabled: boolean) => void;
  reloadPlugins: () => Promise<void>;
  reloadSkills: () => Promise<void>;
}) {
  return (
    <section className="extensions-grid">
      <ManageList
        title="插件"
        subtitle="控制插件是否参与消息分发和工具注册"
        items={plugins}
        reload={reloadPlugins}
        toggle={togglePlugin}
      />

      <ManageList
        title="Skills"
        subtitle="包括内置 Skill、用户 Skill 和 Agent 生成的 Skill"
        items={skills}
        reload={reloadSkills}
        toggle={toggleSkill}
      />
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="key-value">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function channelDisplayName(name: string): string {
  if (name === "wechat_ilink") return "iLink 通道";
  if (name === "wechat869") return "869 通道";
  return name;
}

function channelStatusEntries(name: string, status: AdapterStatus): Array<[string, unknown]> {
  if (name === "wechat_ilink") {
    return [
      ["登录状态", status.logged_in],
      ["Token", status.token_configured],
      ["Base URL", status.base_url],
      ["Bot wxid", status.bot_wxid],
      ["Bot 昵称", status.bot_nickname],
      ["Cursor", status.cursor_set],
      ["轮询", status.polling],
      ["二维码缓存", status.login_qrcode_cached],
    ];
  }
  if (name === "wechat869") {
    return [
      ["登录支持", status.login_supported],
      ["登录状态", status.logged_in ?? status.login_status],
      ["Host", status.host],
      ["Port", status.port],
      ["WebSocket", status.ws_url],
      ["Admin Key", status.admin_key || status.admin_key_configured],
      ["Token Key", status.token_key || status.token_key_configured],
      ["Auth Key", status.auth_key],
      ["Poll Key", status.poll_key],
      ["Bot wxid", status.bot_wxid],
      ["Bot 昵称", status.bot_nickname],
      ["设备类型", status.device_type],
      ["设备 ID", status.device_id],
      ["媒体", status.media_enabled],
      ["仅文本", status.text_only],
    ];
  }
  return Object.entries(status)
    .filter(([key]) => !["adapter", "platform", "error"].includes(key))
    .slice(0, 12)
    .map(([key, value]) => [key, value]);
}

function formatStatusValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "-";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function isImageUrl(value?: string): boolean {
  if (!value) return false;
  return value.startsWith("data:image/") || /^https?:\/\//i.test(value);
}

function ManageList<T extends { name: string; version: string; description: string; enabled: boolean }>({
  title,
  subtitle,
  items,
  reload,
  toggle,
}: {
  title: string;
  subtitle: string;
  items: T[];
  reload: () => Promise<void>;
  toggle: (name: string, enabled: boolean) => void;
}) {
  return (
    <div className="panel table-panel">
      <div className="panel-title panel-title--with-action">
        <div>
          <span>{title}</span>
          <small>{subtitle}</small>
        </div>
        <button className="ghost-button" onClick={() => void reload()}>
          <RefreshCw size={14} />
          重载
        </button>
      </div>
      <div className="manage-scroll">
        {items.length === 0 ? (
          <EmptyState title={`暂无${title}`} text="重载后仍为空，请检查目录和配置。" />
        ) : (
          items.map((item) => (
            <article key={item.name} className="manage-item">
              <div className="manage-item__main">
                <div className="manage-item__title">
                  <span>{item.name}</span>
                  <small>{item.version}</small>
                </div>
                <p>{item.description || "无描述"}</p>
              </div>
              <div className="manage-item__actions">
                <StatusPill label={item.enabled ? "启用" : "停用"} tone={item.enabled ? "ok" : "neutral"} />
                <button className="ghost-button" onClick={() => toggle(item.name, item.enabled)}>
                  {item.enabled ? "停用" : "启用"}
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}

function BackgroundTasks({
  tasks,
  replayTask,
  cancelTask,
  refresh,
}: {
  tasks: BackgroundTask[];
  replayTask: (taskId: string) => void;
  cancelTask: (taskId: string) => void;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="panel table-panel">
      <div className="panel-title panel-title--with-action">
        <span>后台任务</span>
        <button className="ghost-button" onClick={() => void refresh()}>
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>类型</th>
              <th>状态</th>
              <th>来源</th>
              <th>描述</th>
              <th>时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length === 0 ? (
              <tr>
                <td colSpan={7}>暂无数据</td>
              </tr>
            ) : (
              tasks.map((item) => (
                <tr key={item.id}>
                  <td title={item.id}>{shortId(item.id)}</td>
                  <td>{item.kind}</td>
                  <td><StatusPill label={item.status} tone={taskTone(item.status)} /></td>
                  <td>{item.source}</td>
                  <td>{item.description}</td>
                  <td>{formatDate(item.created_at)}</td>
                  <td>
                    <div className="row-actions">
                      <button className="icon-button" title="重放" onClick={() => replayTask(item.id)}>
                        <RotateCcw size={14} />
                      </button>
                      {item.status === "running" || item.status === "pending" ? (
                        <button className="icon-button danger" title="取消" onClick={() => cancelTask(item.id)}>
                          <XCircle size={14} />
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Schedules({
  jobs,
  name,
  setName,
  schedule,
  setSchedule,
  input,
  setInput,
  timezone,
  setTimezone,
  maxRuns,
  setMaxRuns,
  createJob,
  updateJob,
  refresh,
}: {
  jobs: ScheduledJob[];
  name: string;
  setName: (value: string) => void;
  schedule: string;
  setSchedule: (value: string) => void;
  input: string;
  setInput: (value: string) => void;
  timezone: string;
  setTimezone: (value: string) => void;
  maxRuns: string;
  setMaxRuns: (value: string) => void;
  createJob: () => Promise<void>;
  updateJob: (action: "pause" | "resume" | "run" | "delete", jobId: string) => void;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="schedule-grid">
      <div className="panel schedule-create-panel">
        <div className="panel-title">创建定时任务</div>
        <div className="schedule-form">
          <label>
            <span>名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="可选，例如：每日总结" />
          </label>
          <label>
            <span>计划</span>
            <input value={schedule} onChange={(event) => setSchedule(event.target.value)} placeholder="30m / every 2h / daily 09:00 / 0 9 * * *" />
          </label>
          <label>
            <span>时区</span>
            <input value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="Asia/Shanghai" />
          </label>
          <label>
            <span>最大次数</span>
            <input value={maxRuns} onChange={(event) => setMaxRuns(event.target.value.replace(/\D/g, ""))} placeholder="留空不限" />
          </label>
          <label className="schedule-form__input">
            <span>任务内容</span>
            <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="到时间后让 Agent 执行什么？" />
          </label>
          <button className="primary-button" disabled={!schedule.trim() || !input.trim()} onClick={() => void createJob()}>
            <CalendarClock size={15} />
            创建任务
          </button>
        </div>
      </div>

      <div className="panel table-panel">
        <div className="panel-title panel-title--with-action">
          <span>定时任务</span>
          <button className="ghost-button" onClick={() => void refresh()}>
            <RefreshCw size={14} />
            刷新
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>启用</th>
                <th>计划</th>
                <th>下次运行</th>
                <th>次数</th>
                <th>来源</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={8}>暂无数据</td>
                </tr>
              ) : (
                jobs.map((item) => (
                  <tr key={item.id}>
                    <td title={item.id}>{item.name}</td>
                    <td><StatusPill label={item.enabled ? "启用" : "暂停"} tone={item.enabled ? "ok" : "neutral"} /></td>
                    <td>{item.schedule_display}</td>
                    <td>{item.next_run_at ? formatDate(item.next_run_at) : "-"}</td>
                    <td>{String(item.run_count)}</td>
                    <td>{item.source}</td>
                    <td>{item.last_status || "-"}</td>
                    <td>
                      <div className="row-actions">
                        <button className="icon-button" title="立即运行" onClick={() => updateJob("run", item.id)}>
                          <Play size={14} />
                        </button>
                        <button
                          className="icon-button"
                          title={item.enabled ? "暂停" : "恢复"}
                          onClick={() => updateJob(item.enabled ? "pause" : "resume", item.id)}
                        >
                          {item.enabled ? <Pause size={14} /> : <Play size={14} />}
                        </button>
                        <button className="icon-button danger" title="删除" onClick={() => updateJob("delete", item.id)}>
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function SettingsView({
  token,
  setToken,
  themeMode,
  setThemeMode,
  saveToken,
  clearToken,
}: {
  token: string;
  setToken: (value: string) => void;
  themeMode: ThemeMode;
  setThemeMode: (value: ThemeMode) => void;
  saveToken: () => void;
  clearToken: () => void;
}) {
  return (
    <section className="settings-grid">
      <div className="panel settings-panel">
        <div className="panel-title">控制台访问</div>
        <div className="settings-form">
          <label>
            <span>API Base</span>
            <input value={apiBase()} readOnly />
          </label>
          <label>
            <span>WebSocket</span>
            <input value={wsUrl()} readOnly />
          </label>
          <label>
            <span>API Token</span>
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              type="password"
              placeholder="XBOT_API_TOKEN"
              autoComplete="current-password"
            />
          </label>
          <div className="settings-actions">
            <button className="primary-button" disabled={!token.trim()} onClick={saveToken}>
              <KeyRound size={15} />
              保存 Token
            </button>
            <button className="ghost-button" onClick={clearToken}>
              清除
            </button>
          </div>
        </div>
      </div>
      <div className="panel settings-panel">
        <div className="panel-title">界面偏好</div>
        <div className="settings-form">
          <label>
            <span>主题</span>
            <Segmented
              value={themeMode}
              onChange={setThemeMode}
              options={[
                ["system", "跟随系统"],
                ["light", "日间"],
                ["dark", "夜间"],
              ]}
            />
          </label>
        </div>
      </div>
      <div className="panel settings-panel">
        <div className="panel-title">运行说明</div>
        <div className="settings-copy">
          <p>通道、插件和 Skill 的开关会写入后端数据库，重启后继续生效。</p>
          <p>模型密钥、通道 token、数据库连接等敏感配置仍放在 `.env`，避免从浏览器直接写入明文密钥。</p>
          <p>生产环境建议启用 `XBOT_API_AUTH_ENABLED=true`，并通过 HTTPS 访问控制台。</p>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric panel">
      <div className="metric__label">{label}</div>
      <div className="metric__value">{value}</div>
    </div>
  );
}

function DataTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>暂无数据</td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (value: T) => void; options: Array<[T, string]> }) {
  return (
    <div className="segmented">
      {options.map(([option, label]) => (
        <button key={option} className={value === option ? "segmented__item segmented__item--active" : "segmented__item"} onClick={() => onChange(option)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function StatusPill({ label, tone }: { label: string; tone: "ok" | "warn" | "neutral" }) {
  return (
    <span className={`status-pill status-pill--${tone}`}>
      {tone === "ok" ? <CheckCircle2 size={14} /> : <Circle size={12} />}
      {label}
    </span>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <div>{title}</div>
      <p>{text}</p>
    </div>
  );
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function stringify(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}...` : value;
}

function taskTone(status: string): "ok" | "warn" | "neutral" {
  if (["completed", "success"].includes(status)) return "ok";
  if (["running", "pending"].includes(status)) return "warn";
  return "neutral";
}
