import {
  Activity,
  Bot,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  FileText,
  KeyRound,
  LogIn,
  ShieldAlert,
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
  Sparkles,
  Sun,
  Trash2,
  Users,
  Wrench,
  XCircle,
} from "lucide-react";
import { Component, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiBase, clearApiToken, getApiToken, setApiToken, wsUrl } from "../api";
import type {
  AdapterInfo,
  AdapterStatus,
  AgentEvent,
  AgentMemoryInfo,
  AgentTask,
  AgentTaskDetail,
  AgentTaskTimelineItem,
  AgentTaskToolCall,
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
  WechatConversation,
  WechatMember,
  WechatMessage,
  WechatUserDetail,
} from "../types";

type View = "agentChat" | "chat" | "wechat" | "profiles" | "groupOps" | "overview" | "agent" | "tasks" | "channels" | "extensions" | "background" | "schedules" | "logs" | "settings";
type DeliveryMode = "console" | "channel";
type ThemeMode = "system" | "light" | "dark";
type ConsoleMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

const QUICK_EMOJIS = ["😀", "😂", "😊", "😍", "😭", "😅", "👍", "🙏", "🎉", "🔥", "玫瑰", "强", "握手", "OK"];

const navItems: Array<{ id: View; label: string; icon: typeof MessagesSquare }> = [
  { id: "agentChat", label: "Agent 对话", icon: Bot },
  { id: "chat", label: "对话", icon: MessagesSquare },
  { id: "wechat", label: "微信", icon: MessagesSquare },
  { id: "profiles", label: "画像", icon: Users },
  { id: "groupOps", label: "群管", icon: ShieldAlert },
  { id: "overview", label: "总览", icon: Activity },
  { id: "agent", label: "Agent", icon: Bot },
  { id: "tasks", label: "任务", icon: Activity },
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
  const [view, setView] = useState<View>("agentChat");
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
  const [wechatConversations, setWechatConversations] = useState<WechatConversation[]>([]);
  const [wechatMessages, setWechatMessages] = useState<WechatMessage[]>([]);
  const [wechatMembers, setWechatMembers] = useState<WechatMember[]>([]);
  const [wechatUserDetail, setWechatUserDetail] = useState<WechatUserDetail | null>(null);
  const [wechatUnread, setWechatUnread] = useState<Record<string, number>>({});
  const wechatLastMessageRef = useRef<Record<string, string>>({});
  const [profileConversationId, setProfileConversationId] = useState("__all");
  const [profileSearch, setProfileSearch] = useState("");
  const [profileMembers, setProfileMembers] = useState<WechatMember[]>([]);
  const [profileDetails, setProfileDetails] = useState<Record<string, WechatUserDetail>>({});
  const [groupOpsConversationId, setGroupOpsConversationId] = useState("");
  const [groupOpsMembers, setGroupOpsMembers] = useState<WechatMember[]>([]);
  const [groupOpsDetails, setGroupOpsDetails] = useState<Record<string, WechatUserDetail>>({});
  const [groupOpsMessages, setGroupOpsMessages] = useState<WechatMessage[]>([]);
  const [groupOpsFilter, setGroupOpsFilter] = useState("");
  const [selectedConversationId, setSelectedConversationId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [consoleMessagesByContext, setConsoleMessagesByContext] = useState<Record<string, ConsoleMessage[]>>({});
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedAgentSessionSource, setSelectedAgentSessionSource] = useState("terminal:control-ui");
  const [selectedTaskDetail, setSelectedTaskDetail] = useState<AgentTaskDetail | null>(null);
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
  const directConsoleMessages = consoleMessagesByContext[agentConsoleContextKey(selectedAgentSessionSource)] ?? [];
  const channelConsoleMessages = consoleMessagesByContext[consoleContextKey] ?? [];
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
      const load = async <T,>(label: string, promise: Promise<T>, fallback: T): Promise<T> => {
        try {
          return await promise;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.toLowerCase().includes("unauthorized")) throw err;
          console.warn(`[xbot-ui] ${label} load failed:`, message);
          return fallback;
        }
      };
      const [
        nextStatus,
        nextAdapters,
        nextPlugins,
        nextSkills,
        nextConversations,
        nextWechatConversations,
        nextEvents,
        nextTasks,
        nextTools,
        nextLlmStatus,
        nextMcpStatus,
        nextMemories,
        nextBackground,
        nextSchedules,
      ] = await Promise.all([
          load("system/status", api.status(), null),
          load("adapters", api.adapters(), []),
          load("plugins", api.plugins(), []),
          load("skills", api.skills(), []),
          load("conversations", api.conversations(), []),
          load("wechat/conversations", api.wechatConversations(200), []),
          load("agent/events", api.agentEvents(80), []),
          load("agent/tasks", api.agentTasks(80), []),
          load("agent/tools", api.tools(), []),
          load("agent/llm/status", api.llmStatus(), null),
          load("agent/mcp/status", api.mcpStatus(), null),
          load("agent/memories", api.memories(50), []),
          load("agent/background-tasks", api.backgroundTasks(50), []),
          load("agent/scheduled-jobs", api.scheduledJobs(100), []),
        ]);
      setStatus(nextStatus);
      setAdapters(nextAdapters);
      setPlugins(nextPlugins);
      setSkills(nextSkills);
      setConversations(nextConversations);
      setWechatConversations(nextWechatConversations);
      setEvents(nextEvents);
      setAgentTasks(nextTasks);
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
  }, [selectedConversationId, selectedTaskId]);

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
      setWechatMessages([]);
      setWechatMembers([]);
      return;
    }
    if (view === "wechat") {
      api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch((err) => setError(err instanceof Error ? err.message : String(err)));
      api.wechatMembers(selectedConversationId).then(setWechatMembers).catch((err) => setError(err instanceof Error ? err.message : String(err)));
      return;
    }
    api
      .messages(selectedConversationId, 100)
      .then(setMessages)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedConversationId, view]);

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTaskDetail(null);
      return;
    }
    api
      .agentTaskDetail(selectedTaskId)
      .then(setSelectedTaskDetail)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedTaskId]);

  useEffect(() => {
    const socket = new WebSocket(wsUrl());
    socket.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data) as UiEvent;
        setLiveEvents((current) => [item, ...current].slice(0, 100));
        if (item.type === "agent.event") {
          const agentEvent = item.data as AgentEvent;
          setEvents((current) => [agentEvent, ...current].slice(0, 200));
          if (agentEvent.task_id === selectedTaskId) {
            void api.agentTaskDetail(agentEvent.task_id).then(setSelectedTaskDetail).catch(() => undefined);
          }
          if (agentEvent.type === "task.completed") {
            void api.agentTasks(80).then(setAgentTasks).catch(() => undefined);
          }
        }
        if (item.type === "message.created") {
          const payload = item.data as { message?: WechatMessage };
          const incoming = payload.message;
          if (incoming?.conversation_id === selectedConversationId) {
            void api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch(() => undefined);
            void api.wechatMembers(selectedConversationId).then(setWechatMembers).catch(() => undefined);
            setMessages((current) => current.some((m) => m.id === incoming.id) ? current : [...current, incoming]);
          } else if (incoming?.conversation_id) {
            setWechatUnread((current) => ({ ...current, [incoming.conversation_id]: (current[incoming.conversation_id] || 0) + 1 }));
          }
          void api.wechatConversations(200).then(applyWechatConversations).catch(() => undefined);
        }
        if (item.type === "background_task.updated") {
          void api.backgroundTasks(50).then(setBackgroundTasks).catch(() => undefined);
        }
      } catch {
        // Ignore malformed event frames.
      }
    };
    socket.onerror = () => {
      setLiveEvents((current) => [
        {
          id: makeClientId(),
          type: "ui.websocket_error",
          topic: "ui",
          data: {},
          created_at: new Date().toISOString(),
        },
        ...current,
      ]);
    };
    return () => socket.close();
  }, [wsRevision, selectedTaskId, selectedConversationId]);

  useEffect(() => {
    if (view !== "wechat" || !selectedConversationId) return;
    const timer = window.setInterval(() => {
      void api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch(() => undefined);
      void api.wechatMembers(selectedConversationId).then(setWechatMembers).catch(() => undefined);
      void api.wechatConversations(200).then(applyWechatConversations).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [view, selectedConversationId]);

  useEffect(() => {
    if (view !== "profiles") return;
    if (!profileConversationId) setProfileConversationId("__all");
  }, [view, wechatConversations, profileConversationId]);

  useEffect(() => {
    if (view !== "profiles" || !profileConversationId) return;
    let cancelled = false;
    setProfileMembers([]);
    setProfileDetails({});
    if (profileConversationId === "__all") {
      api.wechatUsers(500, profileSearch)
        .then((users) => {
          if (cancelled) return;
          const members = users.map((user) => ({
            user_id: user.contact.user_id,
            nickname: user.contact.nickname,
            remark: user.contact.remark,
            avatar_url: user.contact.avatar_url,
            message_count: user.stats.message_count,
            last_active_at: user.profile.updated_at || null,
          }));
          setProfileMembers(members);
          setProfileDetails(Object.fromEntries(users.map((user) => [user.contact.user_id, user])));
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
      return () => { cancelled = true; };
    }
    api.wechatMembers(profileConversationId)
      .then(async (members) => {
        if (cancelled) return;
        const ordered = members.slice().sort((a, b) => (b.message_count || 0) - (a.message_count || 0));
        setProfileMembers(ordered);
        const details = await Promise.all(
          ordered.slice(0, 80).map(async (member) => {
            try {
              return [member.user_id, await api.wechatUser(member.user_id, profileConversationId)] as const;
            } catch {
              return null;
            }
          }),
        );
        if (!cancelled) setProfileDetails(Object.fromEntries(details.filter(Boolean) as Array<readonly [string, WechatUserDetail]>));
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => { cancelled = true; };
  }, [view, profileConversationId, profileSearch]);

  useEffect(() => {
    if (view !== "groupOps") return;
    const groups = wechatConversations.filter((item) => item.scope === "group");
    if (!groupOpsConversationId && groups[0]) setGroupOpsConversationId(groups[0].id);
  }, [view, wechatConversations, groupOpsConversationId]);

  useEffect(() => {
    if (view !== "groupOps" || !groupOpsConversationId) return;
    let cancelled = false;
    setGroupOpsMembers([]);
    setGroupOpsDetails({});
    setGroupOpsMessages([]);
    api.wechatMessages(groupOpsConversationId, 500).then((items) => { if (!cancelled) setGroupOpsMessages(sortWechatMessages(items)); }).catch(() => undefined);
    api.wechatMembers(groupOpsConversationId)
      .then(async (members) => {
        if (cancelled) return;
        const ordered = members.slice().sort((a, b) => (b.message_count || 0) - (a.message_count || 0));
        setGroupOpsMembers(ordered);
        const details = await Promise.all(
          ordered.slice(0, 100).map(async (member) => {
            try {
              return [member.user_id, await api.wechatUser(member.user_id, groupOpsConversationId)] as const;
            } catch {
              return null;
            }
          }),
        );
        if (!cancelled) setGroupOpsDetails(Object.fromEntries(details.filter(Boolean) as Array<readonly [string, WechatUserDetail]>));
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => { cancelled = true; };
  }, [view, groupOpsConversationId]);

  const requiresToken = error.toLowerCase().includes("unauthorized");

  async function sendMessage() {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");
    setError("");
    const isDirectAgentChat = view === "agentChat";
    const directSource = selectedAgentSessionSource || "terminal:control-ui";
    const contextKey = isDirectAgentChat ? agentConsoleContextKey(directSource) : selectedConversationId || "control-ui";
    const previousConsoleMessages = consoleMessagesByContext[contextKey] ?? [];
    if (isDirectAgentChat) setSelectedAgentSessionSource(directSource);
    const userMessage: ConsoleMessage = {
      id: makeClientId(),
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    const pendingMessage: ConsoleMessage = {
      id: makeClientId(),
      role: "assistant",
      content: "正在交给 Hermes Agent 执行...",
      created_at: new Date().toISOString(),
    };
    setConsoleMessagesByContext((current) => ({
      ...current,
      [contextKey]: [...(current[contextKey] ?? []), userMessage, pendingMessage],
    }));
    const contextBlock = isDirectAgentChat
      ? text
      : selectedConversation
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
      const result = await api.sendAgentTask(contextBlock, isDirectAgentChat ? directSource : "terminal:control-ui");
      setSelectedTaskId(result.task_id);
      if (isDirectAgentChat) setSelectedAgentSessionSource(result.source || directSource);
      const assistantMessage: ConsoleMessage = {
        id: pendingMessage.id,
        role: "assistant",
        content: result.output || "Agent 没有返回文本结果，请查看右侧活动流。",
        created_at: result.created_at,
      };
      setConsoleMessagesByContext((current) => ({
        ...current,
        [contextKey]: (current[contextKey] ?? []).map((message) =>
          message.id === pendingMessage.id ? assistantMessage : message,
        ),
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
      api.agentTaskDetail(result.task_id).then(setSelectedTaskDetail).catch(() => undefined);
      api.agentTasks(80).then(setAgentTasks).catch(() => undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setConsoleMessagesByContext((current) => ({
        ...current,
        [contextKey]: (current[contextKey] ?? []).map((item) =>
          item.id === pendingMessage.id
            ? { ...item, content: `执行失败：${message}`, created_at: new Date().toISOString() }
            : item,
        ),
      }));
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

  async function saveWechatProfile(userId: string, conversationId: string | null, summary: string, tags: string[]) {
    const updated = await api.updateWechatProfile(userId, { conversation_id: conversationId, summary, tags });
    setWechatUserDetail((current) => current?.contact.user_id === userId ? updated : current);
    setProfileDetails((current) => ({ ...current, [userId]: updated }));
    setGroupOpsDetails((current) => ({ ...current, [userId]: updated }));
    return updated;
  }

  function openWechatConversation(id: string) {
    setSelectedConversationId(id);
    setWechatUnread((current) => {
      if (!current[id]) return current;
      const next = { ...current };
      delete next[id];
      return next;
    });
  }

  function applyWechatConversations(next: WechatConversation[]) {
    const previous = wechatLastMessageRef.current;
    const latest: Record<string, string> = {};
    const increments: Record<string, number> = {};
    for (const conversation of next) {
      const lastId = conversation.last_message?.id ? String(conversation.last_message.id) : "";
      if (!lastId) continue;
      latest[conversation.id] = lastId;
      const oldId = previous[conversation.id];
      const incoming = conversation.last_message;
      const outgoing = incoming?.raw?.direction === "outgoing";
      if (oldId && oldId !== lastId && conversation.id !== selectedConversationId && !outgoing) {
        increments[conversation.id] = (increments[conversation.id] || 0) + 1;
      }
    }
    wechatLastMessageRef.current = { ...previous, ...latest };
    if (Object.keys(increments).length) {
      setWechatUnread((current) => {
        const merged = { ...current };
        for (const [id, count] of Object.entries(increments)) merged[id] = (merged[id] || 0) + count;
        return merged;
      });
    }
    setWechatConversations(next);
  }

  return (
    <div className={`shell shell--${view}`}>
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
          <StatusPill label={status?.engine?.state ?? "unknown"} tone={status?.engine?.state === "running" ? "ok" : "warn"} />
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
        <PageErrorBoundary resetKey={view}>
        {view === "agentChat" && (
          <AgentConsoleView
            consoleMessages={directConsoleMessages}
            input={input}
            setInput={setInput}
            sendMessage={sendMessage}
            busy={busy}
            selectedConversation={undefined}
            clearConversationContext={() => undefined}
            detail={selectedTaskDetail}
            tasks={agentTasks}
            selectedTaskId={selectedTaskId}
            selectedAgentSessionSource={selectedAgentSessionSource}
            setSelectedAgentSessionSource={setSelectedAgentSessionSource}
            setSelectedTaskId={setSelectedTaskId}
            events={events}
            liveEvents={liveEvents}
            refreshTasks={async () => {
              const next = await api.agentTasks(80);
              setAgentTasks(next);
              if (selectedTaskId) setSelectedTaskDetail(await api.agentTaskDetail(selectedTaskId));
            }}
          />
        )}
        {view === "chat" && (
          <ChatView
            conversations={filteredConversations}
            query={query}
            setQuery={setQuery}
            selectedConversationId={selectedConversationId}
            setSelectedConversationId={setSelectedConversationId}
            deleteConversation={deleteConversation}
            messages={messages}
            consoleMessages={channelConsoleMessages}
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
        {view === "wechat" && (
          <WechatWorkbench
            conversations={wechatConversations.filter((item) => {
              const text = query.trim().toLowerCase();
              return !text || [item.id, item.title, item.raw_id, item.last_message?.content].filter(Boolean).some((value) => String(value).toLowerCase().includes(text));
            })}
            query={query}
            setQuery={setQuery}
            selectedConversationId={selectedConversationId}
            setSelectedConversationId={openWechatConversation}
            unread={wechatUnread}
            messages={wechatMessages}
            members={wechatMembers}
            userDetail={wechatUserDetail}
            loadUser={async (userId) => setWechatUserDetail(await api.wechatUser(userId, selectedConversationId))}
            clearUser={() => setWechatUserDetail(null)}
            onSend={async (text, file) => {
              const sent = await api.sendWechatMessage(selectedConversationId, { text, file });
              setWechatMessages((current) => sortWechatMessages(current.some((m) => m.id === sent.id) ? current : [...current, sent]));
              void api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch(() => undefined);
              applyWechatConversations(await api.wechatConversations(200));
            }}
            onSync={async () => {
              await api.syncWechatMetadata();
              applyWechatConversations(await api.wechatConversations(200));
              if (selectedConversationId) {
                setWechatMessages(sortWechatMessages(await api.wechatMessages(selectedConversationId, 300)));
                setWechatMembers(await api.wechatMembers(selectedConversationId));
              }
            }}
          />
        )}
        {view === "profiles" && (
          <WechatProfilesView
            conversations={wechatConversations.filter((item) => item.scope === "group")}
            selectedConversationId={profileConversationId}
            setSelectedConversationId={setProfileConversationId}
            members={profileMembers}
            details={profileDetails}
            search={profileSearch}
            setSearch={setProfileSearch}
            onSaveProfile={saveWechatProfile}
          />
        )}
        {view === "groupOps" && (
          <GroupOpsView
            conversations={wechatConversations.filter((item) => item.scope === "group")}
            selectedConversationId={groupOpsConversationId}
            setSelectedConversationId={setGroupOpsConversationId}
            members={groupOpsMembers}
            details={groupOpsDetails}
            messages={groupOpsMessages}
            filter={groupOpsFilter}
            setFilter={setGroupOpsFilter}
            onSaveProfile={saveWechatProfile}
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
        {view === "tasks" && (
          <TaskMonitor
            tasks={agentTasks}
            selectedTaskId={selectedTaskId}
            setSelectedTaskId={setSelectedTaskId}
            detail={selectedTaskDetail}
            refresh={async () => {
              const next = await api.agentTasks(80);
              setAgentTasks(next);
              if (selectedTaskId) setSelectedTaskDetail(await api.agentTaskDetail(selectedTaskId));
            }}
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
        </PageErrorBoundary>
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


function AgentConsoleView({
  consoleMessages,
  input,
  setInput,
  sendMessage,
  busy,
  selectedConversation,
  clearConversationContext,
  detail,
  tasks,
  selectedTaskId,
  selectedAgentSessionSource,
  setSelectedAgentSessionSource,
  setSelectedTaskId,
  events,
  liveEvents,
  refreshTasks,
}: {
  consoleMessages: ConsoleMessage[];
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => void;
  busy: boolean;
  selectedConversation?: Conversation;
  clearConversationContext: () => void;
  detail: AgentTaskDetail | null;
  tasks: AgentTask[];
  selectedTaskId: string;
  selectedAgentSessionSource: string;
  setSelectedAgentSessionSource: (value: string) => void;
  setSelectedTaskId: (value: string) => void;
  events: AgentEvent[];
  liveEvents: UiEvent[];
  refreshTasks: () => Promise<void>;
}) {
  const currentTask = detail?.task;
  const sessionSources = agentSessionSources(tasks);
  const activeSessionSource = selectedAgentSessionSource || "terminal:control-ui";
  const sessionTasks = tasks
    .filter((task) => (task.source || "terminal:control-ui") === activeSessionSource)
    .slice()
    .sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
  const latestSessionTask = sessionTasks[sessionTasks.length - 1];
  const taskStatus = latestSessionTask?.status ?? currentTask?.status ?? (busy ? "running" : "idle");
  const toolCount = detail?.tool_calls?.length ?? 0;
  const timelineCount = detail?.timeline?.length ?? 0;
  const recentEvents = events.filter((event) => !currentTask || event.task_id === taskIdOf(currentTask)).slice(0, 8);
  const transcriptTurns = buildSessionTranscriptTurns(sessionTasks, detail, consoleMessages);

  return (
    <section className="hermes-workspace">
      <aside className="panel hermes-session-pane">
        <div className="hermes-pane-head">
          <div>
            <span>会话</span>
            <small>{sessionSources.length} 个 Agent 会话</small>
          </div>
          <button className="icon-button" onClick={() => void refreshTasks()} title="刷新任务">
            <RefreshCw size={15} />
          </button>
        </div>
        <div className="hermes-session-scroll">
          {sessionSources.map((source) => {
            const sourceTasks = tasks.filter((task) => (task.source || "terminal:control-ui") === source);
            const latest = sourceTasks[0];
            return (
              <button
                key={source}
                className={`hermes-session-card ${activeSessionSource === source ? "hermes-session-card--active" : ""}`}
                onClick={() => {
                  setSelectedAgentSessionSource(source);
                  setSelectedTaskId(latest ? taskIdOf(latest) : "");
                }}
              >
                <div className="hermes-session-card__head">
                  <span>{sessionLabel(source)}</span>
                  <StatusPill label={`${sourceTasks.length} 轮`} tone="neutral" />
                </div>
                <p>{latest?.input || latest?.output || latest?.result || "独立 Agent 对话"}</p>
                <small>{source}</small>
              </button>
            );
          })}
        </div>
      </aside>

      <main className="panel hermes-chat-pane">
        <header className="hermes-chat-header">
          <div className="hermes-avatar">
            <Bot size={19} />
          </div>
          <div className="hermes-chat-title">
            <strong>Hermes Agent</strong>
            <span>
              {selectedConversation
                ? `${selectedConversation.platform}/${selectedConversation.adapter}/${selectedConversation.scope}`
                : `${sessionLabel(activeSessionSource)} · 直接对话`}
            </span>
          </div>
          <div className="hermes-chat-header__meta">
            <StatusPill label={taskStatus} tone={taskTone(taskStatus)} />
            <span>{toolCount} 工具</span>
            <span>{timelineCount} 轨迹</span>
          </div>
        </header>

        {selectedConversation ? (
          <div className="hermes-context-bar">
            <div>
              已带入通道上下文：{selectedConversation.raw_id}
            </div>
            <button className="ghost-button" onClick={clearConversationContext}>
              取消上下文
            </button>
          </div>
        ) : null}

        <div className="hermes-message-scroll">
          {transcriptTurns.length === 0 ? (
            <div className="hermes-welcome">
              <div className="hermes-welcome__mark">
                <Sparkles size={26} />
              </div>
              <h2>和 Agent 直接对话</h2>
              <p>像终端一样直接发给 Agent；工具调用、产物和轨迹会嵌在对话流里。</p>
            </div>
          ) : (
            <>
              {transcriptTurns.map((turn) => (
                <section key={turn.id} className="hermes-turn">
                  <HermesMessageBubble message={turn.user} />
                  <HermesInlineTrace detail={turn.detail} recentEvents={turn.recentEvents ?? []} liveEvents={turn.liveEvents ?? []} />
                  {turn.assistant ? <HermesMessageBubble message={turn.assistant} /> : null}
                </section>
              ))}
            </>
          )}
        </div>

        <footer className="hermes-composer">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入任务或问题，Ctrl/Cmd + Enter 发送"
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                void sendMessage();
              }
            }}
          />
          <div className="hermes-composer__actions">
            <span>{selectedConversation ? "仅引用通道上下文，不回发" : `当前会话 · ${activeSessionSource}`}</span>
            <button className="primary-button" disabled={busy || !input.trim()} onClick={() => void sendMessage()}>
              <Send size={16} />
              {busy ? "执行中" : "发送"}
            </button>
          </div>
        </footer>
      </main>
    </section>
  );
}


function WechatProfilesView({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  members,
  details,
  search,
  setSearch,
  onSaveProfile,
}: {
  conversations: WechatConversation[];
  selectedConversationId: string;
  setSelectedConversationId: (value: string) => void;
  members: WechatMember[];
  details: Record<string, WechatUserDetail>;
  search: string;
  setSearch: (value: string) => void;
  onSaveProfile: (userId: string, conversationId: string | null, summary: string, tags: string[]) => Promise<WechatUserDetail>;
}) {
  const selected = conversations.find((item) => item.id === selectedConversationId);
  const isAllProfiles = selectedConversationId === "__all";
  const [editingProfile, setEditingProfile] = useState<{ member: WechatMember; detail?: WechatUserDetail } | null>(null);
  const profiled = members.filter((member) => {
    const detail = details[member.user_id];
    return detail?.profile?.summary && detail.profile.summary !== "暂无 AI 用户画像。";
  }).length;

  async function editProfile(member: WechatMember, detail?: WechatUserDetail) {
    setEditingProfile({ member, detail });
  }

  async function saveEditingProfile(summary: string, tags: string[]) {
    if (!editingProfile) return;
    await onSaveProfile(editingProfile.member.user_id, null, summary, tags);
    setEditingProfile(null);
  }

  return (
    <section className="profile-lab">
      <aside className="profile-lab__groups">
        <div className="profile-lab__brand">
          <span>Profile Atlas</span>
          <b>群画像库</b>
          <small>按群查看成员画像、标签和最近活跃。</small>
        </div>
        <div className="profile-lab__group-list">
          <button className={`profile-group ${isAllProfiles ? "active" : ""}`} onClick={() => setSelectedConversationId("__all")}>
            <div className="wechat-session__avatar">全</div>
            <div><b>全部画像</b><span>所有用户 · 可搜索标签/画像</span></div>
          </button>
          {conversations.map((item) => (
            <button
              key={item.id}
              className={`profile-group ${selectedConversationId === item.id ? "active" : ""}`}
              onClick={() => setSelectedConversationId(item.id)}
            >
              <WechatConversationAvatar conversation={item} />
              <div>
                <b>{conversationTitle(item)}</b>
                <span>{item.message_count} 条消息 · {item.raw_id}</span>
              </div>
            </button>
          ))}
        </div>
      </aside>
      <main className="profile-lab__main">
        <header className="profile-lab__hero">
          <div>
            <span className="profile-kicker">成员画像工作台</span>
            <h2>{isAllProfiles ? "全部用户画像" : selected ? conversationTitle(selected) : "选择一个群聊"}</h2>
            <p>{isAllProfiles ? "汇总全部用户，可按昵称、wxid、标签、画像搜索。" : "左侧选择群聊，右侧查看每个成员的 AI 画像、标签、发言量和图片量。"}</p>
            <div className="profile-search"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索昵称、wxid、标签、画像" /></div>
          </div>
          <div className="profile-lab__stats">
            <span><b>{members.length}</b>成员</span>
            <span><b>{profiled}</b>已画像</span>
            <span><b>{members.reduce((sum, item) => sum + (item.message_count || 0), 0)}</b>发言</span>
          </div>
        </header>
        {members.length ? (
          <div className="profile-card-grid">
            {members.map((member) => {
              const detail = details[member.user_id];
              const tags = detail?.profile?.tags || [];
              const summary = detail?.profile?.summary || "暂无 AI 用户画像。";
              return (
                <article className={`profile-card ${summary === "暂无 AI 用户画像。" ? "profile-card--empty" : ""}`} key={member.user_id}>
                  <div className="profile-card__top">
                    <WechatAvatar className="profile-card__avatar" src={member.avatar_url || detail?.contact.avatar_url} text={member.nickname || member.user_id} />
                    <div>
                      <h3>{member.nickname || detail?.contact.nickname || member.user_id}</h3>
                      <p>{member.user_id}</p>
                    </div>
                    <button className="profile-card__edit" onClick={() => void editProfile(member, detail)}>编辑</button>
                  </div>
                  <p className="profile-card__summary">{summary}</p>
                  <div className="profile-card__tags">
                    {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>未打标签</span>}
                  </div>
                  <div className="profile-card__meta">
                    <span>发言 {detail?.stats.message_count ?? member.message_count ?? 0}</span>
                    <span>图片 {detail?.stats.image_count ?? 0}</span>
                    <span>{detail?.profile.updated_at ? formatDate(detail.profile.updated_at) : "未更新"}</span>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState title="暂无成员画像" text="选择左侧群聊，或先在微信页同步群成员。" />
        )}
      </main>
      {editingProfile ? <ProfileEditModal member={editingProfile.member} detail={editingProfile.detail} onClose={() => setEditingProfile(null)} onSave={saveEditingProfile} /> : null}
    </section>
  );
}


function GroupOpsView({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  members,
  details,
  messages,
  filter,
  setFilter,
  onSaveProfile,
}: {
  conversations: WechatConversation[];
  selectedConversationId: string;
  setSelectedConversationId: (value: string) => void;
  members: WechatMember[];
  details: Record<string, WechatUserDetail>;
  messages: WechatMessage[];
  filter: string;
  setFilter: (value: string) => void;
  onSaveProfile: (userId: string, conversationId: string | null, summary: string, tags: string[]) => Promise<WechatUserDetail>;
}) {
  const selected = conversations.find((item) => item.id === selectedConversationId);
  const [opsUserDetail, setOpsUserDetail] = useState<WechatUserDetail | null>(null);
  const [editingProfile, setEditingProfile] = useState<{ member: WechatMember; detail?: WechatUserDetail } | null>(null);
  async function openUser(member: WechatMember, detail?: WechatUserDetail) {
    setOpsUserDetail(detail || await api.wechatUser(member.user_id, selectedConversationId));
  }
  const enriched = members.map((member) => {
    const detail = details[member.user_id];
    const tags = detail?.profile.tags || [];
    const text = `${member.nickname} ${member.user_id} ${tags.join(" ")} ${detail?.profile.summary || ""}`.toLowerCase();
    return { member, detail, tags, risk: groupRiskScore(member, detail), text };
  });
  const shown = enriched.filter((item) => !filter.trim() || item.text.includes(filter.trim().toLowerCase()));
  const riskKeywords = ["广告", "推广", "引流", "私聊", "加我", "代理", "返利", "兼职", "刷单", "投诉", "退款", "骗子", "竞品", "辱骂", "敏感"];
  const keywordHits = messages.flatMap((message) => {
    const content = String(message.content || "");
    const hits = riskKeywords.filter((keyword) => content.includes(keyword));
    return hits.length ? [{ message, hits }] : [];
  }).slice(-30).reverse();
  const msgCountByUser = new Map<string, number>();
  const hourMap = new Map<string, number>();
  for (const message of messages) {
    if (message.sender_id) msgCountByUser.set(message.sender_id, (msgCountByUser.get(message.sender_id) || 0) + 1);
    const hour = formatDate(message.timestamp).slice(11, 13) || "--";
    hourMap.set(hour, (hourMap.get(hour) || 0) + 1);
  }
  const enrichedWithMessageRisk = enriched.map((item) => {
    const keywordRisk = keywordHits.filter((hit) => hit.message.sender_id === item.member.user_id).length * 10;
    return { ...item, risk: Math.min(100, item.risk + keywordRisk) };
  });
  const shownWithRisk = enrichedWithMessageRisk.filter((item) => !filter.trim() || item.text.includes(filter.trim().toLowerCase()));
  const riskUsers = enrichedWithMessageRisk.filter((item) => item.risk >= 60);
  const silentUsers = enrichedWithMessageRisk.filter((item) => (item.member.message_count || 0) <= 1);
  const activeUsers = enrichedWithMessageRisk.slice().sort((a, b) => (msgCountByUser.get(b.member.user_id) || b.member.message_count || 0) - (msgCountByUser.get(a.member.user_id) || a.member.message_count || 0)).slice(0, 8);
  const hourlyTrend = [...hourMap.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-12);
  const dailyReport = {
    messages: messages.length,
    speakers: msgCountByUser.size,
    images: messages.filter((m) => m.type === "image" || (m.attachments || []).some((a) => a.kind === "image")).length,
    keywords: keywordHits.length,
  };
  const aiAdvice = riskUsers.length
    ? `建议优先复核 ${riskUsers.slice(0, 3).map((x) => x.member.nickname || x.member.user_id).join("、")} 的命中消息，再决定提醒、观察或私聊。`
    : keywordHits.length
      ? `当前无高风险成员，但有 ${keywordHits.length} 条关键词命中，建议查看预警列表。`
      : "当前群聊风险较低，建议持续观察活跃度和潜水成员。";

  async function editProfile(member: WechatMember, detail?: WechatUserDetail) {
    setEditingProfile({ member, detail });
  }

  async function saveEditingProfile(summary: string, tags: string[]) {
    if (!editingProfile) return;
    await onSaveProfile(editingProfile.member.user_id, null, summary, tags);
    setEditingProfile(null);
  }

  return (
    <section className="ops-board">
      <aside className="ops-groups">
        <div className="ops-groups__head">
          <ShieldAlert size={20} />
          <div><b>群管理</b><span>风险、活跃、画像联动</span></div>
        </div>
        <div className="ops-group-list">
          {conversations.map((item) => (
            <button key={item.id} className={`ops-group ${item.id === selectedConversationId ? "active" : ""}`} onClick={() => setSelectedConversationId(item.id)}>
              <WechatConversationAvatar conversation={item} />
              <div><b>{conversationTitle(item)}</b><span>{item.message_count} 条消息</span></div>
            </button>
          ))}
        </div>
      </aside>
      <main className="ops-main">
        <header className="ops-hero">
          <div>
            <span>Group Command</span>
            <h2>{selected ? conversationTitle(selected) : "选择群聊"}</h2>
            <p>成员画像、风险提示、活跃排行和每日群报集中在这里。</p>
          </div>
          <div className="ops-metrics">
            <span><b>{members.length}</b>成员</span>
            <span><b>{riskUsers.length}</b>风险</span>
            <span><b>{dailyReport.keywords}</b>预警</span>
          </div>
        </header>
        <section className="ops-report">
          <div><b>AI 群管建议</b><p>{aiAdvice}</p></div>
          <div><b>群日报</b><p>{`消息 ${dailyReport.messages} 条 · 发言 ${dailyReport.speakers} 人 · 图片 ${dailyReport.images} 张 · 预警 ${dailyReport.keywords} 条`}</p></div>
          <div><b>活跃榜</b><p>{activeUsers.length ? activeUsers.map((x) => `${x.member.nickname || x.member.user_id}(${msgCountByUser.get(x.member.user_id) || x.member.message_count})`).join(" / ") : "暂无数据"}</p></div>
          <div><b>关键词预警</b><p>{keywordHits.length ? keywordHits.slice(0, 5).map((x) => `${x.hits.join("/")}：${x.message.sender_name || x.message.sender_id}`).join("；") : "暂无关键词命中。"}</p></div>
          <div><b>活跃趋势</b><p>{hourlyTrend.length ? hourlyTrend.map(([h, n]) => `${h}点 ${n}`).join(" / ") : "暂无趋势数据。"}</p></div>
          <div><b>成员轨迹</b><p>{silentUsers.length ? `潜水成员 ${silentUsers.length} 人；点击成员卡片可查看发言、图片和画像。` : "成员活跃正常。"}</p></div>
        </section>
        <div className="ops-toolbar">
          <div className="ops-search"><Search size={16} /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="搜索昵称、wxid、标签、画像" /></div>
          <span>{shownWithRisk.length} / {members.length}</span>
        </div>
        <div className="ops-table">
          {shownWithRisk.map(({ member, detail, tags, risk }) => (
            <article className="ops-member" key={member.user_id} onClick={() => void openUser(member, detail)} title="点击查看聊天记录和风险依据">
              <WechatAvatar className="ops-member__avatar" src={member.avatar_url || detail?.contact.avatar_url} text={member.nickname || member.user_id} />
              <div className="ops-member__main">
                <div className="ops-member__line"><b>{member.nickname || detail?.contact.nickname || member.user_id}</b><small>{member.user_id}</small></div>
                <p>{detail?.profile.summary || "暂无 AI 用户画像。"}</p>
                <div className="ops-tags">{tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>未打标签</span>}</div>
              </div>
              <div className="ops-member__score">
                <span className={risk >= 60 ? "danger" : risk >= 30 ? "warn" : "ok"}>{risk >= 60 ? "高风险" : risk >= 30 ? "观察" : "正常"}</span>
                <b>{risk}</b>
                <small>发言 {detail?.stats.message_count ?? member.message_count ?? 0} · 图 {detail?.stats.image_count ?? 0}</small>
                <button className="ops-member__edit" onClick={(event) => { event.stopPropagation(); void editProfile(member, detail); }}>编辑画像</button>
                <button className="ops-member__edit" onClick={(event) => { event.stopPropagation(); navigator.clipboard?.writeText(member.user_id); }}>复制 wxid</button>
              </div>
            </article>
          ))}
        </div>
      </main>
      {opsUserDetail ? <WechatMemberModal detail={opsUserDetail} onClose={() => setOpsUserDetail(null)} /> : null}
      {editingProfile ? <ProfileEditModal member={editingProfile.member} detail={editingProfile.detail} onClose={() => setEditingProfile(null)} onSave={saveEditingProfile} /> : null}
    </section>
  );
}

function groupRiskScore(member: WechatMember, detail?: WechatUserDetail): number {
  const text = `${detail?.profile.summary || ""} ${(detail?.profile.tags || []).join(" ")}`;
  let score = 0;
  if (/广告|推广|引流|营销|敏感|攻击|竞争|刷屏|异常/.test(text)) score += 55;
  if ((detail?.stats.image_count || 0) >= 10) score += 18;
  if ((member.message_count || 0) <= 1) score += 8;
  if ((member.message_count || 0) >= 80) score += 12;
  return Math.min(100, score);
}


function WechatWorkbench(props: {
  conversations: WechatConversation[];
  query: string;
  setQuery: (value: string) => void;
  selectedConversationId: string;
  setSelectedConversationId: (value: string) => void;
  unread: Record<string, number>;
  messages: WechatMessage[];
  members: WechatMember[];
  userDetail: WechatUserDetail | null;
  loadUser: (userId: string) => Promise<void>;
  clearUser: () => void;
  onSend: (text: string, file: File | null) => Promise<void>;
  onSync: () => Promise<void>;
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const selectedConversation = props.conversations.find((item) => item.id === props.selectedConversationId);
  const members = props.members;
  const forceScrollBottom = useCallback(() => {
    const node = messageListRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    messageEndRef.current?.scrollIntoView({ block: "end" });
  }, []);
  useEffect(() => {
    forceScrollBottom();
    const raf = window.requestAnimationFrame(forceScrollBottom);
    const timer = window.setTimeout(forceScrollBottom, 120);
    return () => { window.cancelAnimationFrame(raf); window.clearTimeout(timer); };
  }, [props.messages.length, props.selectedConversationId, forceScrollBottom]);
  async function submitWechat() {
    if (!props.selectedConversationId || sending || (!draft.trim() && !file)) return;
    setSending(true);
    try {
      await props.onSend(draft, file);
      setDraft("");
      setFile(null);
    } finally {
      setSending(false);
    }
  }

  function pickEmoji(value: string) {
    const text = value.length <= 2 ? value : `[${value}]`;
    setDraft((current) => `${current}${text}`);
    setEmojiOpen(false);
  }

  async function syncWechat() {
    if (syncing) return;
    setSyncing(true);
    try {
      await props.onSync();
    } finally {
      setSyncing(false);
    }
  }
  return (
    <section className={`wechat-page ${detailOpen ? "wechat-page--detail" : ""} ${drawerOpen ? "wechat-page--drawer-open" : ""}`}>
      <aside className="wechat-rail">
        <div className="wechat-avatar">微</div>
        <div className="wechat-rail__icon active">💬</div>
        <div className="wechat-rail__icon">👥</div>
        <div className="wechat-rail__icon">⚙</div>
      </aside>
      {drawerOpen || detailOpen ? <button className="wechat-drawer-backdrop" onClick={() => { setDrawerOpen(false); setDetailOpen(false); }} aria-label="关闭抽屉" /> : null}
      <aside className="wechat-sessions">
        <div className="wechat-search"><Search size={16} /><input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="搜索会话" /></div>
        <div className="wechat-session-list">
          {props.conversations.map((item) => (
            <button key={item.id} className={`wechat-session ${props.selectedConversationId === item.id ? "active" : ""}`} onClick={() => { props.setSelectedConversationId(item.id); setDrawerOpen(false); }}>
              <div className="wechat-session__avatar-wrap">
                <WechatConversationAvatar conversation={item} />
                {props.unread[item.id] ? <span className="wechat-unread-badge">{props.unread[item.id] > 99 ? "99+" : props.unread[item.id]}</span> : null}
              </div>
              <div className="wechat-session__main"><b>{conversationTitle(item)}</b><span>{item.scope === "group" ? "群聊" : "私聊"} · {item.raw_id}</span></div>
              <small>{formatDate(item.updated_at).slice(5, 16)}</small>
            </button>
          ))}
        </div>
      </aside>
      <main className="wechat-chat">
        <header className="wechat-chat__header">
          <button className="wechat-drawer-button" onClick={() => setDrawerOpen(true)}>会话</button>
          <div><b>{selectedConversation ? conversationTitle(selectedConversation) : "请选择微信会话"}</b>{selectedConversation?.scope === "group" ? <span>（{members.length}）</span> : null}</div>
          <div className="wechat-header-actions">
            <button className="wechat-more" disabled={syncing} onClick={() => void syncWechat()}>{syncing ? "同步中" : "同步"}</button>
            <button className="wechat-more" onClick={() => setDetailOpen((v) => !v)}>•••</button>
          </div>
        </header>
        <div className="wechat-message-list" ref={messageListRef}>
          {props.messages.length ? props.messages.map((message) => <WechatMessage key={`${message.id}-${message.timestamp}`} message={message} />) : <EmptyState title="暂无聊天记录" text="选择左侧微信会话后展示消息。" />}<div ref={messageEndRef} />
        </div>
        <footer className="wechat-input">
          <button className="wechat-emoji-toggle" type="button" onClick={() => setEmojiOpen((value) => !value)}>😊</button>
          {emojiOpen ? <div className="wechat-emoji-panel">{QUICK_EMOJIS.map((emoji) => <button key={emoji} type="button" onClick={() => pickEmoji(emoji)}>{emoji}</button>)}</div> : null}
          <label className="wechat-file-button">📁<input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
          <span>✂</span>
          <input value={file ? `${draft}${draft ? " · " : ""}已选文件：${file.name}` : draft} onChange={(event) => setDraft(event.target.value)} placeholder="输入消息/表情，支持图片/文件" onKeyDown={(event) => { if (event.key === "Enter") void submitWechat(); }} />
          <button disabled={sending || (!draft.trim() && !file)} onClick={() => void submitWechat()}>{sending ? "发送中" : "发送"}</button>
        </footer>
      </main>
      {detailOpen ? (
        <aside className="wechat-detail">
          <div className="wechat-search"><Search size={16} /><input placeholder="搜索群成员" /></div>
          <div className="wechat-member-grid">
            {members.slice(0, 24).map((member) => (
              <button key={member.user_id} className="wechat-member" onClick={() => void props.loadUser(member.user_id)}>
                <WechatAvatar className="wechat-member__avatar" src={member.avatar_url} text={member.nickname || member.user_id} /><span>{member.nickname || member.user_id}</span>
              </button>
            ))}
            <button className="wechat-member"><div className="wechat-member__avatar dashed">＋</div><span>添加</span></button>
          </div>
          <div className="wechat-info-row"><b>群聊名称</b><span>{selectedConversation ? conversationTitle(selectedConversation) : "-"}</span></div>
          <div className="wechat-info-row"><b>群ID</b><span>{selectedConversation?.raw_id || "-"}</span></div>
          <div className="wechat-info-row"><b>查找聊天内容</b><span>›</span></div>
        </aside>
      ) : null}
      {props.userDetail ? <WechatMemberModal detail={props.userDetail} onClose={props.clearUser} /> : null}
    </section>
  );
}

function WechatConversationAvatar({ conversation }: { conversation: WechatConversation }) {
  const avatars = conversation.avatar_members || [];
  if (conversation.avatar_url) return <img className="wechat-session__avatar" src={conversation.avatar_url} />;
  if (conversation.scope === "group" && avatars.length) {
    return <div className="wechat-session__avatar wechat-session__avatar--group">{avatars.slice(0, 4).map((src) => <img key={src} src={src} />)}</div>;
  }
  return <div className="wechat-session__avatar">{conversationInitial(conversation)}</div>;
}

function WechatMessage({ message }: { message: WechatMessage }) {
  const images = extractMessageImages(message);
  const emoji = extractWechatEmoji(message);
  const text = displayMessageContent(message, images.length > 0 || Boolean(emoji));
  const outgoing = message.raw?.direction === "outgoing";
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  return (
    <article className={`wechat-message ${outgoing ? "wechat-message--outgoing" : ""}`}>
      <WechatAvatar className="wechat-message__avatar" src={message.sender_avatar_url} text={message.sender_name || message.sender_id || "?"} />
      <div className="wechat-message__main">
        <div className="wechat-message__name">{message.sender_name || message.sender_id}<span>{formatDate(message.timestamp)}</span></div>
        <div className={`wechat-bubble ${emoji ? "wechat-bubble--emoji" : ""}`}>
          {text ? <span>{renderEmojiAliases(text)}</span> : null}
          {emoji ? <WechatEmojiCard emoji={emoji} /> : null}
          {images.map((src) => <button className="wechat-bubble-image" key={src} onClick={() => setPreviewImage(src)}><img src={src} /></button>)}
        </div>
      </div>
      {previewImage ? <div className="wechat-image-preview" onClick={(event) => { event.stopPropagation(); setPreviewImage(null); }}><img src={previewImage} /></div> : null}
    </article>
  );
}

function WechatAvatar({ className, src, text }: { className: string; src?: string | null; text: string }) {
  return src ? <img className={className} src={src} /> : <div className={className}>{(text || "?").slice(0, 1).toUpperCase()}</div>;
}

function ProfileEditModal({
  member,
  detail,
  onClose,
  onSave,
}: {
  member: WechatMember;
  detail?: WechatUserDetail;
  onClose: () => void;
  onSave: (summary: string, tags: string[]) => Promise<void>;
}) {
  const [summary, setSummary] = useState(detail?.profile.summary === "暂无 AI 用户画像。" ? "" : (detail?.profile.summary || ""));
  const [tagsText, setTagsText] = useState((detail?.profile.tags || []).join(", "));
  const [saving, setSaving] = useState(false);
  const name = member.nickname || detail?.contact.nickname || member.user_id;
  async function submit() {
    if (saving) return;
    setSaving(true);
    try {
      const tags = tagsText.split(/[，,]/).map((item) => item.trim()).filter(Boolean);
      await onSave(summary.trim(), tags);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="wechat-modal-backdrop" onClick={onClose}>
      <div className="wechat-modal profile-edit-modal" onClick={(event) => event.stopPropagation()}>
        <button className="wechat-modal__close" onClick={onClose}>×</button>
        <div className="wechat-profile-head"><WechatAvatar className="wechat-profile-avatar" src={member.avatar_url || detail?.contact.avatar_url} text={name} /><div><h3>编辑画像</h3><p>{name} · {member.user_id}</p></div></div>
        <label className="profile-edit-field"><span>用户画像</span><textarea value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="输入/修改用户画像" /></label>
        <label className="profile-edit-field"><span>标签</span><input value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="多个标签用逗号分隔，例如：活跃, 潜在客户" /></label>
        <div className="profile-edit-actions"><button onClick={onClose}>取消</button><button className="primary-button" disabled={saving} onClick={() => void submit()}>{saving ? "保存中" : "保存"}</button></div>
      </div>
    </div>
  );
}

function WechatMemberModal({ detail, onClose }: { detail: WechatUserDetail; onClose: () => void }) {
  const member = detail.contact;
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  return (
    <div className="wechat-modal-backdrop" onClick={onClose}>
      <div className="wechat-modal" onClick={(event) => event.stopPropagation()}>
        <button className="wechat-modal__close" onClick={onClose}>×</button>
        <div className="wechat-profile-head"><WechatAvatar className="wechat-profile-avatar" src={member.avatar_url} text={member.nickname || member.user_id} /><div><h3>{member.nickname || member.user_id}</h3><p>{member.user_id}</p></div></div>
        <div className="wechat-profile-stats"><span>发言 {detail.stats.message_count}</span><span>图片 {detail.stats.image_count}</span><span>标签 {detail.profile.tags.length}</span></div>
        <section><b>AI 用户画像</b><p>{detail.profile.summary}</p><div className="wechat-tags">{detail.profile.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></section>
        <section><b>图片记录</b><div className="wechat-image-grid">{detail.images.slice(0, 24).map((item) => item.url ? <button key={item.id} onClick={() => setPreviewImage(item.url || "")}><img src={item.url} /></button> : null)}</div></section>
        <section><b>最近发言</b><div className="wechat-profile-messages">{detail.recent_messages.slice(-30).map((m) => <p key={`${m.id}-${m.timestamp}`}>{m.content || `[${m.type}]`}</p>)}</div></section>
      </div>
      {previewImage ? <div className="wechat-image-preview" onClick={(event) => { event.stopPropagation(); setPreviewImage(null); }}><img src={previewImage} /></div> : null}
    </div>
  );
}


function conversationTitle(item: Conversation): string { return item.title || item.raw_id || item.id; }
function conversationInitial(item: Conversation): string { return conversationTitle(item).slice(0, 1).toUpperCase(); }
function sortWechatMessages(items: WechatMessage[]): WechatMessage[] {
  return [...items].sort((a, b) => {
    const at = Date.parse(a.timestamp || "") || 0;
    const bt = Date.parse(b.timestamp || "") || 0;
    if (at !== bt) return at - bt;
    return String(a.id).localeCompare(String(b.id));
  });
}
function displayMessageContent(message: Message | WechatMessage, hasMedia = false): string {
  const content = String(message.content || "").trim();
  if (hasMedia && (!content || /^\[(图片|image|动画表情|表情|非文本消息 MsgType=47)\]$/i.test(content))) return "";
  if (content.includes("<emoji") || content.includes("<msg")) return hasMedia ? "" : "[动画表情]";
  return content || (hasMedia ? "" : `[${message.type}]`);
}

type WechatEmojiInfo = { url?: string; md5?: string; name?: string };

function extractWechatEmoji(message: Message | WechatMessage): WechatEmojiInfo | null {
  const raw = message.raw || {};
  const content = String(message.content || "");
  const rawText = JSON.stringify(raw);
  const source = [content, rawText].join("\n");
  if (!source.includes("<emoji") && !source.includes("cdnurl") && !source.includes("emoticonmd5") && !/MsgType[=\": ]+47/i.test(source)) return null;
  const pick = (names: string[]) => {
    for (const name of names) {
      const match = source.match(new RegExp(`${name}=["']([^"']+)["']`, "i"));
      if (match?.[1]) return decodeXmlAttr(match[1]);
    }
    return "";
  };
  const url = pick(["cdnurl", "thumburl", "url"]);
  const md5 = pick(["md5", "emoticonmd5", "encrypturl"]);
  const name = pick(["name", "desc", "title"]) || "动画表情";
  return { url, md5, name };
}

function WechatEmojiCard({ emoji }: { emoji: WechatEmojiInfo }) {
  return <div className="wechat-emoji-card">{emoji.url ? <img src={emoji.url} /> : <span>😄</span>}<small>{emoji.name || "动画表情"}{emoji.md5 ? ` · ${emoji.md5.slice(0, 8)}` : ""}</small></div>;
}

function renderEmojiAliases(text: string): ReactNode[] {
  const map: Record<string, string> = { 微笑: "🙂", 呲牙: "😁", 破涕为笑: "😂", 笑哭: "😂", 强: "👍", 弱: "👎", 玫瑰: "🌹", 爱心: "❤️", 握手: "🤝", OK: "👌", 庆祝: "🎉" };
  const parts = String(text).split(/(\[[^\]]{1,8}\])/g);
  return parts.map((part, index) => {
    const key = part.replace(/^\[|\]$/g, "");
    return map[key] ? <span className="wechat-inline-emoji" key={index}>{map[key]}</span> : <span key={index}>{part}</span>;
  });
}

function decodeXmlAttr(value: string): string {
  return value.replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
}

function extractMessageImages(message: Message | WechatMessage): string[] {
  const raw = message.raw || {};
  const values: string[] = [];
  const attachments = "attachments" in message ? message.attachments : [];
  for (const item of attachments || []) {
    if (item.kind === "image" && item.url) values.push(item.url);
  }
  const scan = (value: unknown) => {
    if (!value) return;
    if (typeof value === "string") {
      const src = normalizeImageSrc(value);
      if (src) values.push(src);
      return;
    }
    if (Array.isArray(value)) value.forEach(scan);
    else if (typeof value === "object") Object.values(value as Record<string, unknown>).forEach(scan);
  };
  scan(raw.attachments); scan(raw.quote_attachments); scan(raw.media); scan(raw.media_url); scan(raw.url);
  return [...new Set(values)].slice(0, 8);
}
function normalizeImageSrc(value: string): string {
  const src = value.trim().replace(/\\/g, "/");
  if (!src) return "";
  if (src.startsWith("data:image/") || src.startsWith("/files/") || src.startsWith("/media/") || /^https?:\/\//i.test(src)) {
    return /\.(png|jpe?g|gif|webp)(\?|$)/i.test(src) || src.startsWith("data:image/") ? src : "";
  }
  return "";
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

function HermesMessageBubble({ message }: { message: ConsoleMessage }) {
  const isAssistant = message.role === "assistant";
  return (
    <article className={`hermes-message ${isAssistant ? "hermes-message--assistant" : "hermes-message--user"}`}>
      <div className="hermes-message__avatar">{isAssistant ? <Bot size={16} /> : "你"}</div>
      <div className="hermes-message__main">
        <div className="hermes-message__meta">
          <span>{isAssistant ? "Agent" : "你"}</span>
          <small>{formatDate(message.created_at)}</small>
        </div>
        <div className="hermes-message__body chat-text">{renderChatContent(message.content)}</div>
      </div>
    </article>
  );
}




type HermesTranscriptTurn = {
  id: string;
  user: ConsoleMessage;
  assistant?: ConsoleMessage;
  detail: AgentTaskDetail | null;
  recentEvents?: AgentEvent[];
  liveEvents?: UiEvent[];
};

function buildSessionTranscriptTurns(
  tasks: AgentTask[],
  selectedDetail: AgentTaskDetail | null,
  liveMessages: ConsoleMessage[],
): HermesTranscriptTurn[] {
  const turns: HermesTranscriptTurn[] = tasks.map((task) => {
    const taskId = taskIdOf(task);
    const detail = selectedDetail?.task && taskIdOf(selectedDetail.task) === taskId ? selectedDetail : taskDetailFromTask(task);
    const output = task.output || task.result || "";
    return {
      id: taskId,
      user: { id: `${taskId}-input`, role: "user" as const, content: task.input || "", created_at: task.created_at },
      assistant: output || task.status === "running"
        ? { id: `${taskId}-output`, role: "assistant" as const, content: output || "任务仍在执行中...", created_at: task.updated_at || task.created_at }
        : undefined,
      detail,
    };
  }).filter((turn) => turn.user.content || turn.assistant);
  const pendingUserIndex = liveMessages.findIndex((message) => message.role === "user" && !turns.some((turn) => turn.user.content === message.content));
  if (pendingUserIndex >= 0) {
    const user = liveMessages[pendingUserIndex];
    if (user?.role === "user") {
      const assistant = liveMessages.slice(pendingUserIndex + 1).find((message) => message.role === "assistant");
      turns.push({ id: user.id, user, assistant, detail: selectedDetail });
    }
  }
  return turns;
}

function taskDetailFromTask(task: AgentTask): AgentTaskDetail {
  return { task, events: [], timeline: [], tool_calls: [], repairs: [], artifacts: [], summary: {} };
}

function agentConsoleContextKey(source: string): string {
  return `agent:${source || "terminal:control-ui"}`;
}

function agentSessionSources(tasks: AgentTask[]): string[] {
  const sources = new Set<string>(["terminal:control-ui"]);
  for (const task of tasks) sources.add(task.source || "terminal:control-ui");
  return [...sources];
}

function sessionLabel(source: string): string {
  if (source === "terminal:control-ui") return "页面直接对话";
  return source.replace(/^terminal:/, "");
}

function tasksToConsoleMessages(tasks: AgentTask[]): ConsoleMessage[] {
  return tasks.flatMap((task) => taskToConsoleMessages(task));
}

function taskToConsoleMessages(task: AgentTask): ConsoleMessage[] {
  const taskId = taskIdOf(task);
  const messages: ConsoleMessage[] = [];
  if (task.input) messages.push({ id: `${taskId}-input`, role: "user", content: task.input, created_at: task.created_at });
  const output = task.output || task.result || "";
  if (output || task.status === "running") {
    messages.push({ id: `${taskId}-output`, role: "assistant", content: output || "任务仍在执行中...", created_at: task.updated_at || task.created_at });
  }
  return messages;
}

function mergeConsoleMessages(persisted: ConsoleMessage[], live: ConsoleMessage[]): ConsoleMessage[] {
  if (live.length === 0) return persisted;
  const seen = new Set(persisted.map((message) => `${message.role}:${message.content}`));
  const merged = [...persisted];
  for (const message of live) {
    const key = `${message.role}:${message.content}`;
    if (!seen.has(key) || message.content.includes("正在交给 Hermes Agent 执行")) merged.push(message);
  }
  return merged;
}

function taskDetailToConsoleMessages(detail: AgentTaskDetail): ConsoleMessage[] {
  const task = detail.task;
  const taskId = taskIdOf(task);
  const messages: ConsoleMessage[] = [];
  if (task.input) {
    messages.push({ id: `${taskId}-input`, role: "user", content: task.input, created_at: task.created_at });
  }
  for (const [index, event] of (detail.events ?? detail.timeline ?? []).entries()) {
    if (event.type === "task.continue_requested") {
      messages.push({ id: `${taskId}-continue-user-${index}`, role: "user", content: String(event.content || ""), created_at: event.created_at });
    }
    if (event.type === "task.continue_completed" || event.type === "task.completed") {
      const content = String(event.content || "");
      if (content && !messages.some((message) => message.role === "assistant" && message.content === content)) {
        messages.push({ id: `${taskId}-assistant-${index}`, role: "assistant", content, created_at: event.created_at });
      }
    }
  }
  if (!messages.some((message) => message.role === "assistant")) {
    messages.push({
      id: `${taskId}-output`,
      role: "assistant",
      content: task.output || task.result || (task.status === "running" ? "任务仍在执行中..." : "Agent 没有返回文本结果。"),
      created_at: task.updated_at || task.created_at,
    });
  }
  return messages;
}

function HermesInlineTrace({
  detail,
  recentEvents,
  liveEvents,
}: {
  detail: AgentTaskDetail | null;
  recentEvents: AgentEvent[];
  liveEvents: UiEvent[];
}) {
  if (!detail) return null;
  const task = detail.task;
  const toolCalls = detail.tool_calls ?? [];
  const artifacts = detail.artifacts ?? [];
  const repairs = detail.repairs ?? [];
  const live = liveEvents.map((event) => ({
    task_id: event.id,
    type: event.type,
    content: event.data,
    created_at: event.created_at,
  } satisfies AgentEvent));
  return (
    <section className="hermes-trace-stream" aria-label="工具与轨迹">
      <div className="hermes-trace-stream__rail">
        <Wrench size={15} />
        <span>Agent 工具轨迹</span>
        <StatusPill label={task.status || "unknown"} tone={taskTone(task.status || "")} />
      </div>
      {toolCalls.map((call, index) => <InlineToolCall key={`${toolCallName(call)}-${index}`} call={call} index={index} latest={index === toolCalls.length - 1} />)}
      {artifacts.map((artifact) => (
        <article key={artifact.id} className="hermes-inline-artifact">
          <FileText size={15} />
          <div><strong>{artifact.kind}</strong><p>{artifact.summary || artifact.path}</p></div>
        </article>
      ))}
      {repairs.map((repair, index) => (
        <article key={`${repair.tool}-${index}`} className="hermes-inline-artifact hermes-inline-artifact--repair">
          <RotateCcw size={15} />
          <div><strong>{repair.tool || repair.error_type || "repair"}</strong><p>{repair.guidance || repair.error}</p></div>
        </article>
      ))}
      {[...recentEvents, ...live].slice(0, 6).map((event, index) => (
        <details key={`${event.task_id}-${event.type}-${index}`} className="hermes-inline-event">
          <summary><span>{event.type}</span><small>{formatDate(event.created_at)}</small></summary>
          <pre>{stringify(event.content)}</pre>
        </details>
      ))}
    </section>
  );
}

function InlineToolCall({ call, index, latest }: { call: AgentTaskToolCall; index: number; latest: boolean }) {
  const status = toolCallStatus(call);
  const content = eventContent(call);
  return (
    <details className={`hermes-inline-tool hermes-inline-tool--${status}`} open={latest || status === "failed"}>
      <summary>
        <span className="hermes-inline-tool__prompt">$ tool run</span>
        <strong>{toolCallName(call)}</strong>
        <StatusPill label={status} tone={taskTone(status)} />
      </summary>
      <div className="hermes-inline-tool__body">
        <div className="hermes-tool-meta"><span>#{index + 1}</span><span>{formatDate(call.started_at ?? eventTimestamp(call))}</span></div>
        {toolCallError(call) ? <div className="tool-error">{toolCallError(call)}</div> : null}
        <label>输入</label><pre>{stringify(call.input ?? content?.input ?? content?.payload ?? content?.arguments ?? {})}</pre>
        <label>输出</label><pre>{stringify(call.output ?? call.fallback ?? content?.output ?? content?.result ?? content ?? {})}</pre>
      </div>
    </details>
  );
}


function renderChatContent(text: string): ReactNode[] {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const fence = line.match(/^```(\w+)?\s*$/);
    if (fence) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) code.push(lines[i++]);
      i += i < lines.length ? 1 : 0;
      nodes.push(<pre key={`code-${i}`}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      nodes.push(
        level === 1 ? <h1 key={`h-${i}`}>{renderInline(heading[2])}</h1> :
        level === 2 ? <h2 key={`h-${i}`}>{renderInline(heading[2])}</h2> :
        <h3 key={`h-${i}`}>{renderInline(heading[2])}</h3>,
      );
      i += 1;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
      nodes.push(<blockquote key={`q-${i}`}>{renderChatContent(quote.join("\n"))}</blockquote>);
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*+]\s+/, ""));
      nodes.push(<ul key={`ul-${i}`}>{items.map((item, n) => <li key={n}>{renderInline(item)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ""));
      nodes.push(<ol key={`ol-${i}`}>{items.map((item, n) => <li key={n}>{renderInline(item)}</li>)}</ol>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i]) && !/^(#{1,3})\s+/.test(lines[i]) && !/^>\s?/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) para.push(lines[i++]);
    nodes.push(<p key={`p-${i}`}>{renderInline(para.join("\n"))}</p>);
  }
  return nodes.length ? nodes : [<span key="empty" className="markdown-plain-text-fallback">{text}</span>];
}

function renderInline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index! > last) parts.push(text.slice(last, match.index));
    const raw = match[0];
    if (raw.startsWith("**")) parts.push(<strong key={match.index}>{raw.slice(2, -2)}</strong>);
    else if (raw.startsWith("`")) parts.push(<code key={match.index}>{raw.slice(1, -1)}</code>);
    else {
      const m = raw.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      parts.push(<a key={match.index} href={m?.[2]} target="_blank" rel="noreferrer">{m?.[1] || raw}</a>);
    }
    last = match.index! + raw.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
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

function ToolTracePanel({
  detail,
  recentEvents,
  liveEvents,
  refresh,
}: {
  detail: AgentTaskDetail | null;
  recentEvents: AgentEvent[];
  liveEvents: UiEvent[];
  refresh: () => Promise<void>;
}) {
  const task = detail?.task;
  const taskId = task ? taskIdOf(task) : "";
  const toolCalls = detail?.tool_calls ?? [];
  const repairs = detail?.repairs ?? [];
  const artifacts = detail?.artifacts ?? [];
  const timeline = detail?.timeline ?? [];

  return (
    <>
      <div className="hermes-tool-header">
        <div>
          <span>工具与轨迹</span>
          <small>{taskId ? shortId(taskId) : "等待任务"}</small>
        </div>
        <button className="icon-button" onClick={() => void refresh()} title="刷新轨迹">
          <RefreshCw size={15} />
        </button>
      </div>

      {!detail ? (
        <div className="hermes-tool-empty">
          <Wrench size={28} />
          <strong>暂无任务轨迹</strong>
          <p>发送消息或从左侧选择任务后，工具调用会在这里单独显示。</p>
        </div>
      ) : (
        <div className="hermes-tool-scroll">
          <section className="hermes-task-card">
            <div className="hermes-task-card__top">
              <div>
                <strong>{shortId(taskId)}</strong>
                <span>{task?.source}</span>
              </div>
              <StatusPill label={task?.status || "unknown"} tone={taskTone(task?.status || "")} />
            </div>
            {task?.output ? <p>{task.output}</p> : <p className="muted">Agent 还没有返回最终文本。</p>}
            <div className="hermes-task-card__stats">
              <span>{toolCalls.length} 工具</span>
              <span>{timeline.length} 事件</span>
              <span>{repairs.length} 修复</span>
            </div>
          </section>

          <section className="hermes-tool-section">
            <div className="hermes-tool-section__title">
              <Wrench size={15} />
              <span>工具调用</span>
            </div>
            {toolCalls.length === 0 ? (
              <div className="hermes-mini-empty">本任务没有工具调用。</div>
            ) : (
              toolCalls.map((call, index) => {
                const status = toolCallStatus(call);
                const content = eventContent(call);
                return (
                  <details
                    key={`${toolCallName(call)}-${index}`}
                    className={`hermes-tool-call hermes-tool-call--${status}`}
                    open={index === toolCalls.length - 1 || status === "failed"}
                  >
                    <summary>
                      <div>
                        <ChevronRight size={14} />
                        <span>{toolCallName(call)}</span>
                      </div>
                      <StatusPill label={status} tone={taskTone(status)} />
                    </summary>
                    <div className="hermes-tool-call__body">
                      <div className="hermes-tool-meta">
                        <span>开始 {formatDate(call.started_at ?? eventTimestamp(call))}</span>
                        <span>结束 {formatDate(call.finished_at)}</span>
                      </div>
                      {toolCallError(call) ? <div className="tool-error">{toolCallError(call)}</div> : null}
                      <label>输入</label>
                      <pre>{stringify(call.input ?? content?.input ?? content?.payload ?? content?.arguments ?? {})}</pre>
                      <label>输出</label>
                      <pre>{stringify(call.output ?? call.fallback ?? content?.output ?? content?.result ?? content ?? {})}</pre>
                    </div>
                  </details>
                );
              })
            )}
          </section>

          {artifacts.length > 0 ? (
            <section className="hermes-tool-section">
              <div className="hermes-tool-section__title">
                <FileText size={15} />
                <span>产物</span>
              </div>
              {artifacts.map((artifact) => (
                <article key={artifact.id} className="hermes-artifact">
                  <strong>{artifact.kind}</strong>
                  <p>{artifact.summary || artifact.path}</p>
                  <small>{formatDate(artifact.created_at)}</small>
                </article>
              ))}
            </section>
          ) : null}

          {repairs.length > 0 ? (
            <section className="hermes-tool-section">
              <div className="hermes-tool-section__title">
                <RotateCcw size={15} />
                <span>自动修复</span>
              </div>
              {repairs.map((repair, index) => (
                <article key={`${repair.tool}-${index}`} className="hermes-repair">
                  <strong>{repair.tool || repair.error_type || "repair"}</strong>
                  <p>{repair.guidance || repair.error}</p>
                </article>
              ))}
            </section>
          ) : null}

          <section className="hermes-tool-section">
            <div className="hermes-tool-section__title">
              <Activity size={15} />
              <span>实时事件</span>
            </div>
            {[...recentEvents, ...liveEvents.map((event) => ({
              task_id: event.id,
              type: event.type,
              content: event.data,
              created_at: event.created_at,
            } satisfies AgentEvent))].slice(0, 10).map((event, index) => (
              <details key={`${event.task_id}-${event.type}-${index}`} className="hermes-event-line">
                <summary>
                  <span>{event.type}</span>
                  <small>{formatDate(event.created_at)}</small>
                </summary>
                <pre>{stringify(event.content)}</pre>
              </details>
            ))}
          </section>
        </div>
      )}
    </>
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

function TaskMonitor({
  tasks,
  selectedTaskId,
  setSelectedTaskId,
  detail,
  refresh,
}: {
  tasks: AgentTask[];
  selectedTaskId: string;
  setSelectedTaskId: (value: string) => void;
  detail: AgentTaskDetail | null;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="task-monitor-grid">
      <div className="panel task-list-panel">
        <div className="panel-title panel-title--with-action">
          <div>
            <span>任务轨迹</span>
            <small>{tasks.length} 个最近任务</small>
          </div>
          <button className="ghost-button" onClick={() => void refresh()}>
            <RefreshCw size={14} />
            刷新
          </button>
        </div>
        <div className="task-list-scroll">
          {tasks.length === 0 ? (
            <EmptyState title="暂无任务" text="页面对话、通道唤醒和后台 Agent 执行后会生成任务轨迹。" />
          ) : (
            tasks.map((task) => (
              <button
                key={taskIdOf(task)}
                className={`task-list-item ${selectedTaskId === taskIdOf(task) ? "task-list-item--active" : ""}`}
                onClick={() => setSelectedTaskId(taskIdOf(task))}
              >
                <div className="task-list-item__head">
                  <strong>{shortId(taskIdOf(task))}</strong>
                  <StatusPill label={task.status} tone={taskTone(task.status)} />
                </div>
                <span>{task.source}</span>
                <p>{task.input || task.output || task.result || "-"}</p>
                <small>{formatDate(task.created_at)}</small>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="panel task-detail-panel">
        <TaskDetailContent detail={detail} refresh={refresh} />
      </div>
    </section>
  );
}

function TaskDetailContent({ detail, refresh }: { detail: AgentTaskDetail | null; refresh: () => Promise<void> }) {
  if (!detail) {
    return <EmptyState title="未选择任务" text="选择任务后，这里会展示对话结果、工具调用、时间线和失败修复建议。" />;
  }
  const timeline = Array.isArray(detail.timeline) ? detail.timeline : [];
  const toolCalls = Array.isArray(detail.tool_calls) ? detail.tool_calls : [];
  const repairs = Array.isArray(detail.repairs) ? detail.repairs : [];
  const artifacts = Array.isArray(detail.artifacts) ? detail.artifacts : [];
  const summary = detail.summary ?? {};
  const task = detail.task;
  const taskId = taskIdOf(task);
  const toolFailed = summary.tool_failed ?? toolCalls.filter((call) => toolCallStatus(call) === "failed").length;
  const llmIterations = summary.llm_iterations ?? timeline.filter((item) => String(item.type ?? "").startsWith("llm.")).length;

  return (
    <>
      <div className="panel-title task-detail-title">
        <div>
          <span>{shortId(taskId)}</span>
          <small>{task.source}</small>
        </div>
        <div className="row-actions">
          <StatusPill label={task.status || "unknown"} tone={taskTone(task.status)} />
          <button
            className="ghost-button"
            onClick={async () => {
              await api.resumeAgentTask(taskId);
              await refresh();
            }}
          >
            <Play size={14} />
            继续
          </button>
        </div>
      </div>
      <div className="task-summary-grid">
        <Metric label="事件" value={String(summary.event_count ?? timeline.length)} />
        <Metric label="工具调用" value={String(summary.tool_started ?? toolCalls.length)} />
        <Metric label="失败" value={String(toolFailed)} />
        <Metric label="LLM 轮次" value={String(llmIterations)} />
      </div>
      <div className="task-detail-scroll">
        {task.output ? (
          <section className="task-section">
            <h3>Agent 回复</h3>
            <div className="assistant-output">{task.output}</div>
          </section>
        ) : null}

        <section className="task-section">
          <h3>工具流</h3>
          {toolCalls.length === 0 ? (
            <p className="muted">这个任务没有工具调用。</p>
          ) : (
            toolCalls.map((call, index) => {
              const status = toolCallStatus(call);
              const content = eventContent(call);
              return (
                <details key={`${toolCallName(call)}-${index}`} className={`tool-call-card tool-call-card--${status}`} open={index === toolCalls.length - 1 || status === "failed"}>
                  <summary>
                    <span>{toolCallName(call)}</span>
                    <StatusPill label={status} tone={taskTone(status)} />
                  </summary>
                  <div className="tool-call-card__body">
                    <KeyValue label="开始" value={formatDate(call.started_at ?? eventTimestamp(call))} />
                    <KeyValue label="结束" value={formatDate(call.finished_at)} />
                    {toolCallError(call) ? <div className="tool-error">{toolCallError(call)}</div> : null}
                    <div className="tool-json-grid">
                      <pre>{stringify(call.input ?? content?.input ?? content?.payload ?? content?.arguments ?? {})}</pre>
                      <pre>{stringify(call.output ?? call.fallback ?? content?.output ?? content?.result ?? content ?? {})}</pre>
                    </div>
                  </div>
                </details>
              );
            })
          )}
        </section>

        {repairs.length > 0 ? (
          <section className="task-section">
            <h3>失败修复建议</h3>
            <div className="repair-list">
              {repairs.map((repair, index) => (
                <article key={`${repair.tool}-${index}`} className="repair-card">
                  <div className="repair-card__head">
                    <strong>{repair.tool || "-"}</strong>
                    <StatusPill label={repair.error_type || "failed"} tone="warn" />
                  </div>
                  <p>{repair.guidance || repair.error}</p>
                  {repair.repair_steps?.length ? (
                    <ol>
                      {repair.repair_steps.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ol>
                  ) : null}
                  {repair.suggested_tool ? (
                    <pre>{stringify({ tool: repair.suggested_tool, payload: repair.suggested_payload })}</pre>
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {artifacts.length > 0 ? (
          <section className="task-section">
            <h3>产物</h3>
            <div className="repair-list">
              {artifacts.map((artifact) => (
                <article key={artifact.id} className="repair-card">
                  <div className="repair-card__head">
                    <strong>{artifact.kind}</strong>
                    <small>{formatDate(artifact.created_at)}</small>
                  </div>
                  <p>{artifact.summary || artifact.path}</p>
                  <pre>{stringify({ path: artifact.path, hash: artifact.content_hash, metadata: artifact.metadata })}</pre>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        <section className="task-section">
          <h3>时间线</h3>
          <div className="timeline-list">
            {timeline.map((item, index) => (
              <details key={`${item.type}-${index}`} className="timeline-item">
                <summary>
                  <span>{item.title || item.type || "event"}</span>
                  <small>{formatDate(item.created_at)}</small>
                </summary>
                <pre>{stringify(item.content)}</pre>
              </details>
            ))}
          </div>
        </section>
      </div>
    </>
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

function makeClientId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function stringify(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}...` : value;
}

function taskIdOf(task: Pick<AgentTask, "task_id" | "id">): string {
  return task.task_id || task.id || "";
}

function taskTone(status: string): "ok" | "warn" | "neutral" {
  if (["completed", "success"].includes(status)) return "ok";
  if (["running", "pending", "started"].includes(status)) return "warn";
  return "neutral";
}

function eventContent(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object") return null;
  const maybeContent = (value as { content?: unknown }).content;
  if (maybeContent && typeof maybeContent === "object") return maybeContent as Record<string, unknown>;
  return value as Record<string, unknown>;
}

function toolCallName(call: AgentTaskToolCall | AgentTaskTimelineItem): string {
  const content = eventContent(call);
  const direct = "tool" in call ? call.tool : undefined;
  const type = "type" in call ? call.type : undefined;
  return String(direct || content?.tool || content?.name || type || "tool");
}

function toolCallStatus(call: AgentTaskToolCall | AgentTaskTimelineItem): string {
  const content = eventContent(call);
  const type = String(("type" in call ? call.type : "") || "");
  const status = "status" in call ? call.status : undefined;
  if (status) return String(status);
  if (content?.status) return String(content.status);
  if (type.includes("failed") || type.includes("error")) return "failed";
  if (type.includes("completed") || type.includes("finished")) return "completed";
  if (type.includes("started")) return "started";
  return "event";
}

function toolCallError(call: AgentTaskToolCall | AgentTaskTimelineItem): string {
  const content = eventContent(call);
  const direct = "error" in call ? call.error : undefined;
  return String(direct || content?.error || content?.message || "");
}

function eventTimestamp(call: AgentTaskToolCall | AgentTaskTimelineItem): string | null {
  return "created_at" in call ? call.created_at : null;
}

type PageErrorBoundaryProps = {
  resetKey: string;
  children: ReactNode;
};

type PageErrorBoundaryState = {
  error: string;
  resetKey: string;
};

class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = { error: "", resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<PageErrorBoundaryState> {
    return { error: error instanceof Error ? error.message : String(error) };
  }

  static getDerivedStateFromProps(props: PageErrorBoundaryProps, state: PageErrorBoundaryState): Partial<PageErrorBoundaryState> | null {
    if (props.resetKey !== state.resetKey) {
      return { error: "", resetKey: props.resetKey };
    }
    return null;
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel page-error">
          <div className="panel-title">页面渲染失败</div>
          <p>{this.state.error}</p>
        </div>
      );
    }
    return this.props.children;
  }
}
