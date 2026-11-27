import {
  Activity,
  ArrowRight,
  Bot,
  BookOpenText,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Copy,
  ExternalLink,
  FileText,
  HardDrive,
  HeartPulse,
  Key,
  Layers,
  LayoutDashboard,
  LogIn,
  MessageCircle,
  MessagesSquare,
  Monitor,
  Moon,
  Network,
  Package,
  PanelsTopLeft,
  Paperclip,
  Play,
  QrCode,
  Radio,
  RefreshCw,
  Search,
  Send,
  Settings,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Store,
  Sun,
  Tag,
  Trash2,
  UserCheck,
  UserRound,
  Users,
  Wrench,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { Component, Fragment, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, clearApiToken, getApiToken, setApiToken, wsUrl } from "../api";
import qqIcon from "../assets/channels/qq.svg";
import telegramIcon from "../assets/channels/telegram.svg";
import wechatIcon from "../assets/channels/weixin.svg";
import { WECHAT_CLIENT_LABEL, wechatChannelDisplayText } from "./wechatChannelLabel";
import type {
  AdapterInfo,
  AdapterStatus,
  AgentEvent,
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
import { AgentWorkspace } from "./AgentWorkspace";
import { ConfigCenter, type ConfigAppliedEvent } from "./ConfigCenter";
import { SettingsHome } from './SettingsHome';
import { version as frontendVersion } from '../../package.json';
import { FrameworkUpdate } from './FrameworkUpdate';
import { HomeDashboard, type WebSocketState } from "./HomeDashboard";
import { PageHeading } from "./IllustrationHero";
import { KnowledgeCenter } from "./KnowledgeCenter";
import { MarkdownContent } from "./MarkdownContent";
import { OperationsCenter } from "./OperationsCenter";
import { OfficialMarketplace } from "./OfficialMarketplace";
import { WechatPersonaPanel } from "./WechatPersonaPanel";

export type View =
  | "home"
  | "agentChat"
  | "wechat"
  | "profiles"
  | "groupOps"
  | "knowledge"
  | "operations"
  | "channels"
  | "extensions"
  | "marketplace"
  | "settings";

type ThemeMode = "system" | "light" | "dark";

const navItems: Array<{ id: View; label: string; icon: typeof LayoutDashboard; desc: string; section: string }> = [
  { id: "home", label: "控制台首页", icon: LayoutDashboard, desc: "运行状态与全局看板", section: "工作区" },
  { id: "agentChat", label: "Agent 对话", icon: Bot, desc: "智能协同与任务执行", section: "工作区" },
  { id: "wechat", label: "微信工作台", icon: MessagesSquare, desc: "会话消息与好友互动", section: "工作区" },
  { id: "profiles", label: "用户画像", icon: Users, desc: "人群标签与深度洞察", section: "用户与内容" },
  { id: "groupOps", label: "社群管理", icon: ShieldAlert, desc: "群成员与风控守护", section: "用户与内容" },
  { id: "knowledge", label: "知识库", icon: BookOpenText, desc: "长期记忆与结构知识", section: "用户与内容" },
  { id: "operations", label: "任务与自动化", icon: CalendarClock, desc: "后台任务、计划与活动流", section: "系统" },
  { id: "channels", label: "接入通道", icon: Network, desc: "协议网关与扫码鉴权", section: "系统" },
  { id: "extensions", label: "扩展与技能", icon: Package, desc: "插件工具箱与能力库", section: "系统" },
  { id: "marketplace", label: "官方市场", icon: Store, desc: "官方插件与技能发行包", section: "系统" },
  { id: "settings", label: "控制台设置", icon: Settings, desc: "系统参数与运行配置", section: "系统" },
];

const THEME_STORAGE_KEY = "xbot.control.theme";

function readThemeMode(): ThemeMode {
  const value = window.localStorage.getItem(THEME_STORAGE_KEY);
  return value === "light" || value === "dark" || value === "system" ? value : "light";
}

export function App() {
  const readView = () => navItems.find(item => `#/${item.id}` === window.location.hash)?.id ?? "home";
  const [view, changeView] = useState<View>(readView);
  function setView(next: View) { window.location.hash = `/${next}`; }
  useEffect(() => {
    const sync = () => changeView(readView());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const [settingsSection, setSettingsSection] = useState("");
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
  const [profilePage, setProfilePage] = useState(1);
  const [profileTotal, setProfileTotal] = useState(0);
  const [profileCursors, setProfileCursors] = useState<Record<number, string>>({ 1: "" });
  const [editingProfileUser, setEditingProfileUser] = useState<WechatUserDetail | null>(null);
  const [groupOpsConversationId, setGroupOpsConversationId] = useState("");
  const [groupOpsMembers, setGroupOpsMembers] = useState<WechatMember[]>([]);
  const [groupOpsDetails, setGroupOpsDetails] = useState<Record<string, WechatUserDetail>>({});
  const [groupOpsMessages, setGroupOpsMessages] = useState<WechatMessage[]>([]);
  const [groupOpsFilter, setGroupOpsFilter] = useState("");
  const [selectedConversationId, setSelectedConversationId] = useState<string>("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [tools, setTools] = useState<AgentToolInfo[]>([]);
  const [liveEvents, setLiveEvents] = useState<UiEvent[]>([]);
  const [apiToken, setApiTokenState] = useState(getApiToken());
  const [themeMode, setThemeMode] = useState<ThemeMode>(readThemeMode);
  const [wsRevision, setWsRevision] = useState(0);
  const [websocketState, setWebsocketState] = useState<WebSocketState>("connecting");
  const [loadErrors, setLoadErrors] = useState<Record<string, string>>({});
  const [loadingAll, setLoadingAll] = useState(true);
  const [adapterToggleBusy, setAdapterToggleBusy] = useState("");
  const [error, setError] = useState("");

  const viewRef = useRef(view);
  const selectedConversationIdRef = useRef(selectedConversationId);
  const stageRef = useRef<HTMLElement>(null);
  viewRef.current = view;
  selectedConversationIdRef.current = selectedConversationId;

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      stageRef.current?.parentElement?.scrollTo({ top: 0, left: 0 });
      stageRef.current?.scrollTo({ top: 0, left: 0 });
      stageRef.current?.querySelector<HTMLElement>(".content-scroll")?.scrollTo({ top: 0, left: 0 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [view]);


  const totalUnreadCount = useMemo(() => {
    return Object.values(wechatUnread).reduce((acc, count) => acc + count, 0);
  }, [wechatUnread]);

  const loadAll = useCallback(async () => {
    setError("");
    setLoadingAll(true);
    try {
      const failures: Array<[string, string]> = [];
      const load = async <T,>(label: string, promise: Promise<T>, apply: (value: T) => void): Promise<void> => {
        try {
          apply(await promise);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.toLowerCase().includes("unauthorized")) throw err;
          console.warn(`[xbot-ui] ${label} load failed:`, message);
          failures.push([label, message]);
        }
      };
      await Promise.all([
        load("system/status", api.status(), setStatus),
        load("adapters", api.adapters(), setAdapters),
        load("plugins", api.plugins(), setPlugins),
        load("skills", api.skills(), setSkills),
        load("conversations", api.conversations(), setConversations),
        load("wechat/conversations", api.wechatConversations(200), (next) => {
          setWechatConversations(next);
          setSelectedConversationId((current) => current || next[0]?.id || "");
        }),
        load("agent/events", api.agentEvents(80), setEvents),
        load("agent/tools", api.tools(), setTools),
      ]);
      setLoadErrors(Object.fromEntries(failures));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingAll(false);
    }
  }, []);

  const handleConfigApplied = useCallback(async ({ apiToken: nextApiToken }: ConfigAppliedEvent) => {
    if (nextApiToken !== undefined) {
      setApiToken(nextApiToken);
      setApiTokenState(nextApiToken.trim());
    }
    setWsRevision((value) => value + 1);
    await loadAll();
  }, [loadAll]);

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
    if (adapters.length === 0) return;
    void Promise.all(adapters.map((adapter) => refreshAdapterStatus(adapter.name)));
  }, [adapters]);

  useEffect(() => {
    if (!selectedConversationId) {
      setWechatMessages([]);
      setWechatMembers([]);
      return;
    }
    if (view === "wechat") {
      api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch((err) => setError(err instanceof Error ? err.message : String(err)));
      api.wechatMembers(selectedConversationId).then(setWechatMembers).catch((err) => setError(err instanceof Error ? err.message : String(err)));
    }
  }, [selectedConversationId, view]);

  useEffect(() => {
    const socket = new WebSocket(wsUrl());
    let closedByEffect = false;
    setWebsocketState("connecting");
    socket.onopen = () => setWebsocketState("connected");
    socket.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data) as UiEvent;
        setLiveEvents((current) => [item, ...current].slice(0, 100));
        if (item.type === "agent.event") {
          const agentEvent = item.data as AgentEvent;
          setEvents((current) => [agentEvent, ...current].slice(0, 200));
        }
        if (item.type === "message.created") {
          const payload = item.data as { message?: WechatMessage };
          const incoming = payload.message;
          if (incoming?.conversation_id === selectedConversationIdRef.current && viewRef.current === "wechat") {
            setWechatMessages((current) => sortWechatMessages([
              ...current.filter((message) => message.id !== incoming.id),
              incoming,
            ]));
          } else if (incoming?.conversation_id && incoming.raw?.direction !== "outgoing") {
            setWechatUnread((current) => ({ ...current, [incoming.conversation_id]: (current[incoming.conversation_id] || 0) + 1 }));
          }
          void api.wechatConversations(200).then(applyWechatConversations).catch(() => undefined);
        }
      } catch {
        // Ignore frame error
      }
    };
    socket.onerror = () => setWebsocketState("error");
    socket.onclose = () => {
      if (!closedByEffect) setWebsocketState((current) => current === "error" ? "error" : "disconnected");
    };
    return () => {
      closedByEffect = true;
      socket.close();
    };
  }, [wsRevision]);

  useEffect(() => {
    if (view !== "wechat" || !selectedConversationId || websocketState === "connected" || websocketState === "connecting") return;
    const timer = window.setInterval(() => {
      void api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch(() => undefined);
      void api.wechatMembers(selectedConversationId).then(setWechatMembers).catch(() => undefined);
      void api.wechatConversations(200).then(applyWechatConversations).catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [view, selectedConversationId, websocketState]);

  useEffect(() => {
    if (view !== "profiles") return;
    if (!profileConversationId) setProfileConversationId("__all");
  }, [view, wechatConversations, profileConversationId]);

  useEffect(() => {
    setProfilePage(1);
    setProfileCursors({ 1: "" });
  }, [profileConversationId, profileSearch]);

  useEffect(() => {
    if (view !== "profiles" || !profileConversationId) return;
    let cancelled = false;
    if (profilePage === 1) {
      setProfileMembers([]);
      setProfileDetails({});
    }
    if (profileConversationId === "__all") {
      if (profileMembers.length && profilePage > 1) return () => { cancelled = true; };
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
          setProfileTotal(members.length);
          setProfileDetails(Object.fromEntries(users.map((user) => [user.contact.user_id, user])));
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
      return () => { cancelled = true; };
    }
    api.wechatProfilePage(profileConversationId, 30, profileCursors[profilePage] || "")
      .then((result) => {
        if (cancelled) return;
        const members = result.items.map((item) => ({
          user_id: item.contact.user_id,
          nickname: item.contact.nickname,
          remark: item.contact.remark,
          avatar_url: item.contact.avatar_url,
          message_count: item.stats.message_count,
          last_active_at: item.last_active_at || null,
        }));
        setProfileMembers(members);
        setProfileTotal(result.total);
        setProfileDetails(Object.fromEntries(result.items.map((item) => [item.contact.user_id, item])));
        if (result.next_cursor) {
          setProfileCursors((current) => ({ ...current, [profilePage + 1]: result.next_cursor || "" }));
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => { cancelled = true; };
  }, [view, profileConversationId, profileSearch, profilePage]);

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

  async function toggleAdapter(name: string, enabled: boolean) {
    if (adapterToggleBusy) return;
    setAdapterToggleBusy(name);
    setError("");
    try {
      const next = enabled ? await api.disableAdapter(name) : await api.enableAdapter(name);
      setAdapters(next);
      await refreshAdapterStatus(name);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAdapterToggleBusy("");
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
      setChannelMessage(next.logged_in ? "iLink 登录成功！" : "尚未确认登录，请在手机端确认后点击再次检查。");
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
      setChannelMessage(wechatChannelDisplayText(String(next.message ?? `${WECHAT_CLIENT_LABEL}登录已发起，请使用微信扫码。`)));
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
      setChannelMessage(next.logged_in ? `${WECHAT_CLIENT_LABEL}已登录。` : "尚未确认登录，请在手机端确认后再次检查。");
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

  async function saveWechatProfile(userId: string, conversationId: string | null, summary: string, tags: string[]) {
    const updated = await api.updateWechatProfile(userId, { conversation_id: conversationId, summary, tags });
    setWechatUserDetail((current) => current?.contact.user_id === userId ? updated : current);
    setProfileDetails((current) => ({ ...current, [userId]: updated }));
    setGroupOpsDetails((current) => ({ ...current, [userId]: updated }));
    setEditingProfileUser(null);
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
      if (oldId && oldId !== lastId && !(view === "wechat" && conversation.id === selectedConversationId) && !outgoing) {
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
      <a className="skip-link" href="#main-stage">跳到主内容</a>
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div>
          <div className="sidebar__brand-card">
            <div className="sidebar__brand-mascot-wrap">
              <img
                src="/assets/illustrations/mascot.png"
                alt=""
                className="sidebar__brand-mascot"
              />
            </div>
            <div className="sidebar__brand-info">
              <div className="sidebar__brand-name">
                <span>xbot</span>
              </div>
              <div className="sidebar__brand-sub">智能工作台</div>
            </div>
          </div>

          <nav className="sidebar__nav" aria-label="主要导航">
            {navItems.map((item, index) => {
              const Icon = item.icon;
              const isActive = view === item.id;
              const unread = item.id === "wechat" ? totalUnreadCount : 0;
              return (
                <Fragment key={item.id}>
                  {(index === 0 || navItems[index - 1].section !== item.section) && <div className="nav__section">{item.section}</div>}
                  <button
                    type="button"
                    className={`nav__item ${isActive ? "nav__item--active" : ""}`}
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => {
                      if (item.id === "settings") setSettingsSection("");
                      setView(item.id);
                    }}
                  >
                    <div className="nav__item-icon-wrap"><Icon size={16} /></div>
                    <span className="nav__item-label">{item.label}</span>
                    {unread > 0 && <span className="nav__item-badge">{unread}</span>}
                  </button>
                </Fragment>
              );
            })}
          </nav>
        </div>

        <div className="sidebar__footer">
          <div className="sidebar__status-pill">
            <span className={`status-dot ${status?.engine?.state === "running" ? "status-dot--ok" : "status-dot--warn"}`} />
            <span>{status?.engine?.state === "running" ? "运行正常" : "等待服务"}</span>
          </div>
          <div className="sidebar__footer-actions">
            <ThemeToggle value={themeMode} onChange={setThemeMode} />
            <button
              type="button"
              className="icon-button"
              onClick={() => void loadAll()}
              title="刷新全部数据"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Stage */}
      <main className="stage" id="main-stage" tabIndex={-1} ref={stageRef}>
        {error ? <div className="error-banner" style={{ margin: "16px 28px 0 28px" }}>{wechatChannelDisplayText(error)}</div> : null}
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
          {view === "home" && (
            <HomeDashboard
              adapters={adapters}
              adapterStatuses={adapterStatuses}
              plugins={plugins}
              skills={skills}
              tools={tools}
              wechatConversationCount={wechatConversations.length}
              unreadCount={totalUnreadCount}
              profileCount={profileTotal || profileMembers.length}
              liveEvents={liveEvents}
              websocketState={websocketState}
              loading={loadingAll}
              loadErrors={loadErrors}
              adapterToggleBusy={adapterToggleBusy}
              onNavigate={setView}
              onRefresh={() => void loadAll()}
              onToggleAdapter={toggleAdapter}
            />
          )}

          {view === "agentChat" && (
            <div className="content-scroll agent-stage">
              <AgentWorkspace
                renderText={(text) => <MarkdownContent text={text} />}
                onSettings={() => {
                  setSettingsSection("agent");
                  setView("settings");
                }}
              />
            </div>
          )}

          {view === "wechat" && (
            <div className="content-scroll">
              <PageHeading
                title="微信工作台"
                tagline="私聊与群聊"
                stats={[
                  { label: "活跃会话", value: wechatConversations.length, tone: "secondary" },
                  { label: "未读消息", value: totalUnreadCount, tone: totalUnreadCount > 0 ? "primary" : "neutral" },
                  { label: "群聊覆盖", value: wechatConversations.filter(c => c.scope === "group").length, tone: "amber" },
                ]}
              />
              <WechatWorkbench
                conversations={wechatConversations}
                selectedConversationId={selectedConversationId}
                setSelectedConversationId={openWechatConversation}
                unread={wechatUnread}
                messages={wechatMessages}
                members={wechatMembers}
                userDetail={wechatUserDetail}
                loadUser={async (userId) => setWechatUserDetail(await api.wechatUser(userId, selectedConversationId))}
                clearUser={() => setWechatUserDetail(null)}
                onEditProfile={(user) => setEditingProfileUser(user)}
                onSend={async (text, file) => {
                  const sent = await api.sendWechatMessage(selectedConversationId, { text, file });
                  setWechatMessages((current) => sortWechatMessages(current.some((m) => m.id === sent.id) ? current : [...current, sent]));
                  void api.wechatMessages(selectedConversationId, 300).then((items) => setWechatMessages(sortWechatMessages(items))).catch(() => undefined);
                  applyWechatConversations(await api.wechatConversations(200));
                }}
                onSync={async () => {
                  const result = await api.syncWechatMetadata();
                  applyWechatConversations(await api.wechatConversations(200));
                  if (selectedConversationId) {
                    const [messages, members] = await Promise.all([
                      api.wechatMessages(selectedConversationId, 300), api.wechatMembers(selectedConversationId),
                    ]);
                    if (selectedConversationIdRef.current === selectedConversationId) {
                      setWechatMessages(sortWechatMessages(messages));
                      setWechatMembers(members);
                    }
                  }
                  return result.private_avatars_received ?? 0;
                }}
              />
            </div>
          )}

          {view === "profiles" && (
            <div className="content-scroll">
              <PageHeading
                title="社群用户画像与洞察"
                tagline="基于历史交互自动提取的成员特质、活跃度分析与个性化标签，打造有温度、有记忆的人格化互动。"
                stats={[
                  { label: "已画像用户", value: profileTotal || profileMembers.length, tone: "amber" },
                  { label: "覆盖群组", value: wechatConversations.filter(c => c.scope === "group").length, tone: "primary" },
                ]}
              />
              <WechatProfilesView
                conversations={wechatConversations.filter((item) => item.scope === "group")}
                selectedConversationId={profileConversationId}
                setSelectedConversationId={setProfileConversationId}
                members={profileMembers}
                details={profileDetails}
                page={profilePage}
                setPage={setProfilePage}
                total={profileTotal}
                serverPaged={profileConversationId !== "__all"}
                search={profileSearch}
                setSearch={setProfileSearch}
                onEditProfile={(user) => setEditingProfileUser(user)}
              />
            </div>
          )}

          {view === "groupOps" && (
            <div className="content-scroll">
              <PageHeading
                title="社群守护与风控运营"
                tagline="群聊活跃度热力分布、违规发言风控与群成员健康度管理，让每一个社群充满秩序与活力。"
                stats={[
                  { label: "当前群成员", value: groupOpsMembers.length, tone: "secondary" },
                  { label: "监控群消息", value: groupOpsMessages.length, tone: "primary" },
                ]}
              />
              <GroupOpsView
                conversations={wechatConversations.filter((item) => item.scope === "group")}
                selectedConversationId={groupOpsConversationId}
                setSelectedConversationId={setGroupOpsConversationId}
                members={groupOpsMembers}
                details={groupOpsDetails}
                messages={groupOpsMessages}
                filter={groupOpsFilter}
                setFilter={setGroupOpsFilter}
                onEditProfile={(user) => setEditingProfileUser(user)}
              />
            </div>
          )}

          {view === "knowledge" && (
            <div className="content-scroll">
              <PageHeading
                title="智慧知识库与记忆晶体"
                tagline="多群聊独立沉淀与自动萃取，构建包含双向链接、实体关联与长期问答的专属知识图谱。"
              />
              <KnowledgeCenter />
            </div>
          )}

          {view === "operations" && (
            <div className="content-scroll">
              <PageHeading
                title="任务与自动化"
                tagline="后台任务、定时计划与实时活动"
              />
              <OperationsCenter events={events} liveEvents={liveEvents} />
            </div>
          )}

          {view === "channels" && (
            <div className="content-scroll">
              <PageHeading
                title="接入通道"
                tagline="通道状态、登录与连接配置"
                stats={[
                  { label: "已配置通道", value: adapters.length, tone: "primary" },
                  { label: "运行中通道", value: adapters.filter(a => a.started).length, tone: "secondary" },
                ]}
              />
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
                onConfigApplied={handleConfigApplied}
              />
            </div>
          )}

          {view === "marketplace" && <OfficialMarketplace />}
          {view === "extensions" && (
            <div className="content-scroll">
              <PageHeading
                title="扩展与技能"
                tagline="管理本机已安装的插件与技能"
                stats={[
                  { label: "已安装插件", value: plugins.length, tone: "purple" },
                  { label: "技能包数量", value: skills.length, tone: "primary" },
                  { label: "可用工具", value: tools.length, tone: "secondary" },
                ]}
              />
              <Extensions
                plugins={plugins}
                skills={skills}
                togglePlugin={togglePlugin}
                toggleSkill={toggleSkill}
                reloadPlugins={async () => setPlugins(await api.reloadPlugins())}
                reloadSkills={async () => setSkills(await api.reloadSkills())}
              />
            </div>
          )}

          {view === "settings" && (
            <div className="content-scroll">
              <PageHeading title="控制台设置" tagline="模型与控制台偏好" />
              <SettingsView
                key={settingsSection}
                onChat={()=>setView('agentChat')}
                status={status}
                themeMode={themeMode}
                setThemeMode={setThemeMode}
                onConfigApplied={handleConfigApplied}
              />
            </div>
          )}
        </PageErrorBoundary>

        {editingProfileUser && (
          <ProfileEditModal
            user={editingProfileUser}
            onClose={() => setEditingProfileUser(null)}
            onSave={saveWechatProfile}
          />
        )}
        {view === 'settings' ? <span className="frontend-version">Xbot v{frontendVersion}</span> : <FrameworkUpdate version={frontendVersion} />}
      </main>
    </div>
  );
}

/* ==========================================================================
   Theme & Auth Components
   ========================================================================== */

function ThemeToggle({ value, onChange }: { value: ThemeMode; onChange: (value: ThemeMode) => void }) {
  const next = value === "system" ? "light" : value === "light" ? "dark" : "system";
  const Icon = value === "system" ? Monitor : value === "light" ? Sun : Moon;
  const label = value === "system" ? "跟随系统" : value === "light" ? "亮色模式" : "暗色模式";
  return (
    <button
      type="button"
      className="icon-button"
      onClick={() => onChange(next)}
      title={`当前主题：${label} (点击切换)`}
    >
      <Icon size={15} />
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
    <div className="modal-backdrop">
      <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="auth-dialog-title" tabIndex={-1} onKeyDown={(event) => trapDialogFocus(event)}>
        <div className="modal-header">
          <h2 className="modal-title" id="auth-dialog-title">需要 API 访问鉴权</h2>
        </div>
        <div className="modal-body">
          <p style={{ color: "var(--text-muted)", marginBottom: 14 }}>
            当前服务端开启了控制台访问令牌校验，请输入管理 Token 以建立连接：
          </p>
          <input
            type="password"
            className="input-text"
            autoFocus
            value={token}
            placeholder="输入管理 Token..."
            onChange={(e) => setToken(e.target.value)}
          />
        </div>
        <div className="modal-footer">
          <button type="button" className="ghost-button" onClick={onClear}>
            清除
          </button>
          <button type="button" className="primary-button" onClick={onSave}>
            保存并连接
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
   View: 微信工作台 (WechatWorkbench)
   ========================================================================== */

function WechatAvatar({ src, fallback }: { src?: string | null; fallback: ReactNode }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  return src && src !== failedSrc
    ? <img src={src} alt="" referrerPolicy="no-referrer" onError={() => setFailedSrc(src)} />
    : <>{fallback}</>;
}

function WechatWorkbench({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  unread,
  messages,
  members,
  userDetail,
  loadUser,
  clearUser,
  onEditProfile,
  onSend,
  onSync,
}: {
  conversations: WechatConversation[];
  selectedConversationId: string;
  setSelectedConversationId: (id: string) => void;
  unread: Record<string, number>;
  messages: WechatMessage[];
  members: WechatMember[];
  userDetail: WechatUserDetail | null;
  loadUser: (userId: string) => Promise<void>;
  clearUser: () => void;
  onEditProfile: (user: WechatUserDetail) => void;
  onSend: (text: string, file?: File) => Promise<void>;
  onSync: () => Promise<number>;
}) {
  const [search, setSearch] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncFeedback, setSyncFeedback] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const timelineEndRef = useRef<HTMLDivElement>(null);

  const filteredConversations = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) =>
      [c.id, c.title, c.raw_id, c.last_message?.content].filter(Boolean).some((val) =>
        String(val).toLowerCase().includes(q),
      ),
    );
  }, [conversations, search]);

  const activeConversation = conversations.find((c) => c.id === selectedConversationId);

  useEffect(() => {
    const timeline = timelineEndRef.current?.parentElement;
    timeline?.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const text = chatInput.trim();
    if (!text || sending) return;
    setSending(true);
    setChatInput("");
    try {
      await onSend(text);
    } finally {
      setSending(false);
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setSending(true);
    try {
      await onSend("", file);
    } finally {
      setSending(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleSync() {
    if (syncing) return;
    setSyncing(true);
    setSyncFeedback("");
    try {
      const received = await onSync();
      setSyncFeedback(received > 0 ? `已获取 ${received} 个私聊头像` : "同步完成，未获取到私聊头像");
    } catch (reason) {
      setSyncFeedback(reason instanceof Error ? `同步失败：${wechatChannelDisplayText(reason.message)}` : "同步失败，请稍后重试");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="wechat-shell">
      {/* Col 1: Conversations list */}
      <div className="wechat-pane">
        <div className="wechat-pane__head">
          <div className="search-field" style={{ flex: 1 }}>
            <Search size={14} />
            <input
              type="text"
              className="search-box"
              placeholder="搜索会话或消息..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={() => void handleSync()}
            title={syncFeedback || "同步微信头像、元数据与联系人"}
            aria-label={syncing ? "正在同步微信头像与联系人" : "同步微信头像、元数据与联系人"}
            disabled={syncing}
          >
            <RefreshCw size={14} className={syncing ? "spin" : ""} />
          </button>
        </div>
        <div role="status">
          {syncFeedback && <div className={`wechat-sync-feedback ${syncFeedback.startsWith("同步失败") ? "is-error" : ""}`}>{syncFeedback}</div>}
        </div>

        <div className="wechat-conv-list">
          {filteredConversations.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state__title">无匹配微信会话</div>
            </div>
          ) : (
            filteredConversations.map((conv) => {
              const count = unread[conv.id] || 0;
              const isSelected = conv.id === selectedConversationId;
              return (
                <div
                  key={conv.id}
                  className={`wechat-conv-item ${isSelected ? "wechat-conv-item--active" : ""}`}
                  onClick={() => setSelectedConversationId(conv.id)}
                >
                  <div className="wechat-conv-avatar">
                    <WechatAvatar src={conv.avatar_url} fallback={conv.avatar_members?.length ? (
                      <span className="wechat-conv-avatar-grid">
                        {conv.avatar_members.slice(0, 4).map((src) => <img key={src} src={src} alt="" />)}
                      </span>
                    ) : (
                      <span>{(conv.title || conv.raw_id || "群").slice(0, 1)}</span>
                    )} />
                    {count > 0 && <span className="wechat-conv-unread">{count}</span>}
                  </div>

                  <div className="wechat-conv-info">
                    <div className="wechat-conv-name">
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {conv.title || conv.raw_id || "未命名会话"}
                      </span>
                      {conv.last_message?.timestamp && (
                        <span className="wechat-conv-time">
                          {formatTimeShort(conv.last_message.timestamp)}
                        </span>
                      )}
                    </div>
                    <div className="wechat-conv-snippet">
                      {conv.last_message?.content || "暂无最新消息"}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Col 2: Chat message stream */}
      <div className="wechat-pane">
        <div className="wechat-pane__head">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>
              {activeConversation?.title || activeConversation?.raw_id || "微信会话"}
            </span>
            {activeConversation?.scope === "group" && (
              <span className="status-pill status-pill--neutral">{members.length} 位群成员</span>
            )}
          </div>
        </div>

        <div className="wechat-chat-timeline">
          {messages.length === 0 ? (
            <div className="empty-state">
              <img src="/assets/illustrations/empty-state.png" alt="" className="empty-state__art" />
              <div className="empty-state__title">暂无消息记录</div>
              <div className="empty-state__text">选择会话或发送新消息开始互动。</div>
            </div>
          ) : (
            messages.map((m) => {
              const isOutgoing = m.raw?.direction === "outgoing";
              return (
                <div
                  key={m.id}
                  className={`wechat-bubble-row ${isOutgoing ? "wechat-bubble-row--outgoing" : ""}`}
                >
                  <div
                    className="wechat-conv-avatar"
                    style={{ width: 34, height: 34, cursor: "pointer" }}
                    onClick={() => void loadUser(m.sender_id)}
                    title="查看用户画像"
                  >
                    <WechatAvatar src={m.sender_avatar_url} fallback={<span>{(m.sender_name || m.sender_id || "?").slice(0, 1)}</span>} />
                  </div>

                  <div>
                    {!isOutgoing && (
                      <span className="wechat-sender-tag">{m.sender_name || m.sender_id}</span>
                    )}
                    <div className="wechat-bubble-box">
                      {m.content}
                    </div>
                    <span className="agent-msg-time" style={{ textAlign: isOutgoing ? "right" : "left" }}>
                      {formatTimeShort(m.timestamp)}
                    </span>
                  </div>
                </div>
              );
            })
          )}
          <div ref={timelineEndRef} />
        </div>

        <div className="agent-composer-dock">
          <div className="agent-input-row">
            <textarea
              className="agent-textarea"
              placeholder="输入微信回复消息 (Enter 发送)..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              rows={1}
            />

            <input
              type="file"
              ref={fileInputRef}
              style={{ display: "none" }}
              onChange={handleFileUpload}
            />

            <button
              type="button"
              className="icon-button"
              title="发送图片/文件"
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip size={15} />
            </button>

            <button
              type="button"
              className="primary-button"
              style={{ padding: "8px 16px" }}
              onClick={handleSend}
              disabled={sending || !chatInput.trim()}
            >
              {sending ? <RefreshCw size={14} className="spin" /> : <Send size={14} />}
              <span>发送</span>
            </button>
          </div>
        </div>
      </div>

      {/* Col 3: Contact & Persona Details */}
      <aside className="wechat-pane">
        <div className="wechat-pane__head">
          <span style={{ fontWeight: 700, fontSize: 13.5 }}>联系人 / 成员画像</span>
          {userDetail && (
            <button
              type="button"
              className="ghost-button"
              style={{ padding: "2px 8px", fontSize: 11 }}
              onClick={clearUser}
            >
              关闭
            </button>
          )}
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          <WechatPersonaPanel conversation={activeConversation} />
          {userDetail ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div className="profile-card__avatar">
                  {userDetail.contact.avatar_url ? (
                    <img src={userDetail.contact.avatar_url} alt="" />
                  ) : (
                    <span>{(userDetail.contact.nickname || "?").slice(0, 1)}</span>
                  )}
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{userDetail.contact.nickname || "未命名"}</div>
                  <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>ID: {userDetail.contact.user_id}</div>
                </div>
              </div>

              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", marginBottom: 6 }}>
                  画像标签
                </div>
                <div className="profile-card__tags">
                  {userDetail.profile.tags && userDetail.profile.tags.length > 0 ? (
                    userDetail.profile.tags.map((tag) => (
                      <span key={tag} className="profile-tag">
                        #{tag}
                      </span>
                    ))
                  ) : (
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>暂无画像标签</span>
                  )}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", marginBottom: 6 }}>
                  交互特征与性格分析
                </div>
                <div
                  style={{
                    padding: 10,
                    background: "var(--bg-surface-soft)",
                    borderRadius: "var(--radius-md)",
                    fontSize: 12.5,
                    lineHeight: 1.6,
                    color: "var(--text-body)",
                  }}
                >
                  {userDetail.profile.summary || "暂无深度画像分析摘要。"}
                </div>
              </div>

              <button
                type="button"
                className="ghost-button"
                onClick={() => onEditProfile(userDetail)}
              >
                <Wrench size={13} /> 编辑画像与个性标签
              </button>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", marginBottom: 10 }}>
                群内成员列表 ({members.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {members.slice(0, 50).map((m) => (
                  <div
                    key={m.user_id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "6px 8px",
                      borderRadius: "var(--radius-sm)",
                      background: "var(--bg-surface-soft)",
                      cursor: "pointer",
                    }}
                    onClick={() => void loadUser(m.user_id)}
                  >
                    <div className="wechat-member-avatar">
                      <WechatAvatar src={m.avatar_url} fallback={<span>{(m.nickname || "?").slice(0, 1)}</span>} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {m.nickname || m.user_id}
                      </div>
                      <div style={{ fontSize: 10.5, color: "var(--text-light)" }}>
                        发言 {m.message_count || 0} 次
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

/* ==========================================================================
   View: 用户画像 (WechatProfilesView)
   ========================================================================== */

function WechatProfilesView({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  members,
  details,
  page,
  setPage,
  total,
  serverPaged,
  search,
  setSearch,
  onEditProfile,
}: {
  conversations: WechatConversation[];
  selectedConversationId: string;
  setSelectedConversationId: (id: string) => void;
  members: WechatMember[];
  details: Record<string, WechatUserDetail>;
  page: number;
  setPage: (p: number | ((p: number) => number)) => void;
  total: number;
  serverPaged: boolean;
  search: string;
  setSearch: (s: string) => void;
  onEditProfile: (user: WechatUserDetail) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        className="card"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          padding: 14,
        }}
      >
        <div className="community-filters">
          <div className="community-picker">
          <select
            aria-label="筛选画像所属社群"
            value={selectedConversationId}
            onChange={(e) => setSelectedConversationId(e.target.value)}
          >
            <option value="__all">全部微信社群成员</option>
            {conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title || c.raw_id}
              </option>
            ))}
          </select>
          <ChevronDown size={15} aria-hidden="true" /></div>

          <div className="search-field" style={{ flex: 1 }}>
            <Search size={14} />
            <input
              type="text"
              className="search-box"
              placeholder="搜索用户昵称、备注或标签..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            共 {total || members.length} 位画像用户
          </span>
          {serverPaged && total > 30 && (
            <div style={{ display: "flex", gap: 4 }}>
              <button
                type="button"
                className="ghost-button"
                style={{ padding: "4px 10px" }}
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </button>
              <button
                type="button"
                className="ghost-button"
                style={{ padding: "4px 10px" }}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="profiles-grid">
        {members.map((m) => {
          const detail = details[m.user_id];
          return (
            <div key={m.user_id} className="profile-card">
              <div className="profile-card__head">
                <div className="profile-card__avatar">
                  {m.avatar_url ? (
                    <img src={m.avatar_url} alt="" />
                  ) : (
                    <span>{(m.nickname || "?").slice(0, 1)}</span>
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {m.nickname || m.user_id}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    发言频次: {m.message_count || 0} 次
                  </div>
                </div>
              </div>

              <div className="profile-card__tags">
                {detail?.profile.tags && detail.profile.tags.length > 0 ? (
                  detail.profile.tags.map((tag) => (
                    <span key={tag} className="profile-tag">
                      #{tag}
                    </span>
                  ))
                ) : (
                  <span style={{ fontSize: 11, color: "var(--text-light)" }}>暂无标签</span>
                )}
              </div>

              <div
                style={{
                  fontSize: 12,
                  color: "var(--text-body)",
                  lineHeight: 1.5,
                  background: "var(--bg-surface-soft)",
                  padding: 8,
                  borderRadius: "var(--radius-sm)",
                  minHeight: 44,
                }}
              >
                {detail?.profile.summary || "等待 Agent 结合多轮互动自动生成画像总结。"}
              </div>

              <button
                type="button"
                className="ghost-button"
                style={{ fontSize: 12, padding: "5px 12px" }}
                onClick={() => detail && onEditProfile(detail)}
              >
                <Tag size={12} /> 编辑个性标签
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ==========================================================================
   View: 社群管理 (GroupOpsView)
   ========================================================================== */

function GroupOpsView({
  conversations,
  selectedConversationId,
  setSelectedConversationId,
  members,
  details,
  messages,
  filter,
  setFilter,
  onEditProfile,
}: {
  conversations: WechatConversation[];
  selectedConversationId: string;
  setSelectedConversationId: (id: string) => void;
  members: WechatMember[];
  details: Record<string, WechatUserDetail>;
  messages: WechatMessage[];
  filter: string;
  setFilter: (s: string) => void;
  onEditProfile: (user: WechatUserDetail) => void;
}) {
  const filteredMembers = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return members;
    return members.filter((m) => (m.nickname || m.user_id).toLowerCase().includes(q));
  }, [members, filter]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="card community-filters community-filters--members">
        <div className="community-picker">
        <select
          aria-label="选择管理的社群"
          value={selectedConversationId}
          onChange={(e) => setSelectedConversationId(e.target.value)}
        >
          {conversations.length === 0 && <option value="">暂无可选社群</option>}
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title || c.raw_id}
            </option>
          ))}
        </select>
        <ChevronDown size={15} aria-hidden="true" /></div>

        <div className="search-field" style={{ flex: 1 }}>
          <Search size={14} />
          <input
            type="text"
            className="search-box"
            placeholder="搜索成员昵称..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>成员信息</th>
              <th>发言活跃度</th>
              <th>画像标签</th>
              <th>最后活跃</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {filteredMembers.map((m) => {
              const detail = details[m.user_id];
              return (
                <tr key={m.user_id}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div className="group-member-avatar">
                        {m.avatar_url ? <img src={m.avatar_url} alt="" /> : <span>{(m.nickname || "?").slice(0, 1)}</span>}
                      </div>
                      <div>
                        <div style={{ fontWeight: 600 }}>{m.nickname || m.user_id}</div>
                        <div style={{ fontSize: 11, color: "var(--text-light)" }}>ID: {m.user_id}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="status-pill status-pill--ok">
                      {m.message_count || 0} 条发言
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {detail?.profile.tags?.map((t) => (
                        <span key={t} className="profile-tag">#{t}</span>
                      )) || <span style={{ color: "var(--text-muted)", fontSize: 11 }}>无</span>}
                    </div>
                  </td>
                  <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {formatTimeShort(m.last_active_at)}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="ghost-button"
                      style={{ fontSize: 11.5, padding: "4px 10px" }}
                      onClick={() => detail && onEditProfile(detail)}
                    >
                      画像管理
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ==========================================================================
   View: 接入通道 (Channels)
   ========================================================================== */

const CHANNEL_ICONS = new Map([
  ["wechat869", wechatIcon],
  ["wechat_ilink", wechatIcon],
  ["qq", qqIcon],
  ["telegram", telegramIcon],
]);

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
  onConfigApplied,
}: {
  adapters: AdapterInfo[];
  adapterStatuses: Record<string, AdapterStatus>;
  ilinkQr: IlinkQrCode | null;
  wechat869Qr: AdapterStatus | null;
  channelBusy: string;
  channelMessage: string;
  toggleAdapter: (name: string, enabled: boolean) => Promise<void>;
  refreshAdapterStatus: (name: string) => Promise<void>;
  startIlinkLogin: () => Promise<void>;
  pollIlinkLogin: () => Promise<void>;
  startWechat869Login: () => Promise<void>;
  pollWechat869Login: () => Promise<void>;
  onConfigApplied: (event: ConfigAppliedEvent) => Promise<void>;
}) {
  const [showQrModal, setShowQrModal] = useState(false);
  const [configAdapter, setConfigAdapter] = useState("");
  const configDialog = useRef<HTMLDialogElement>(null);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {channelMessage && (
        <div style={{ padding: "10px 16px", background: "var(--ok-soft)", color: "var(--ok)", border: "1px solid var(--ok-border)", borderRadius: "var(--radius-md)", fontSize: 13 }}>
          {channelMessage}
        </div>
      )}

      <div className="channels-grid">
        {adapters.map((ad) => {
          const isRunning = ad.started;
          const icon = CHANNEL_ICONS.get(ad.name);
          return (
            <div key={ad.name} className="channel-card">
              <div className="channel-card__head">
                <div className="channel-icon-wrap" data-brand={icon ? ad.name : undefined} aria-hidden="true">
                  {icon ? (
                    <img src={icon} alt="" width={24} height={24} />
                  ) : ad.name === "web" ? (
                    <PanelsTopLeft size={22} />
                  ) : (
                    <Network size={22} />
                  )}
                </div>
                <h3 className="channel-name">{icon ? <button type="button" className="channel-open" title="通道配置"
                    aria-label={`配置${channelDisplayName(ad.name)}`} aria-haspopup="dialog"
                    onClick={() => { setConfigAdapter(ad.name); configDialog.current?.showModal(); }}>
                    {channelDisplayName(ad.name)}
                  </button> : channelDisplayName(ad.name)}</h3>
                <button type="button" role="switch" aria-checked={ad.enabled} className="channel-switch"
                  aria-label={`启用${channelDisplayName(ad.name)}`} title={ad.enabled ? "关闭通道" : "启用通道"}
                  onClick={() => void toggleAdapter(ad.name, ad.enabled)} />
              </div>

              <p className="channel-description">{({wechat869: "微信客户端扫码接入", wechat_ilink: "微信 iLink 扫码接入", qq: "QQ 机器人消息", telegram: "Telegram Bot 消息", web: "网页对话入口"} as Record<string,string>)[ad.name] ?? ad.platform}</p>

              <div className="channel-actions">
                <span className={`status-pill ${isRunning ? "status-pill--ok" : "status-pill--neutral"}`}>{isRunning ? "运行中" : "已停止"}</span>
                {icon && !ad.name.startsWith("wechat") && <span aria-hidden="true">配置 ›</span>}

                {ad.name === "wechat_ilink" && (
                  <button
                    type="button"
                    className="primary-button"
                    style={{ flex: 1, fontSize: 12 }}
                    onClick={() => {
                      setShowQrModal(true);
                      void startIlinkLogin();
                    }}
                  >
                    <QrCode size={13} /> 扫码登录
                  </button>
                )}

                {ad.name === "wechat869" && (
                  <button
                    type="button"
                    className="primary-button"
                    style={{ flex: 1, fontSize: 12 }}
                    onClick={() => {
                      setShowQrModal(true);
                      void startWechat869Login();
                    }}
                  >
                    <QrCode size={13} /> 扫码授权
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <dialog ref={configDialog} className="channel-config-dialog" aria-labelledby="channel-config-title"
        onClose={event => { if (event.target === event.currentTarget) setConfigAdapter(""); }}>
        <header className="modal-header">
          <h2 className="modal-title" id="channel-config-title">{channelDisplayName(configAdapter)}配置</h2>
          <button type="button" className="icon-button" aria-label="关闭通道配置" autoFocus onClick={() => configDialog.current?.close()}><X size={16} /></button>
        </header>
        {configAdapter && <ConfigCenter key={configAdapter} scope="channels" channel={configAdapter} onApplied={onConfigApplied} />}
      </dialog>

      {showQrModal && (
        <div className="modal-backdrop" onClick={() => setShowQrModal(false)}>
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="channel-qr-title" tabIndex={-1} onClick={(e) => e.stopPropagation()} onKeyDown={(event) => trapDialogFocus(event, () => setShowQrModal(false))}>
            <div className="modal-header">
              <h2 className="modal-title" id="channel-qr-title">微信通道扫码登录</h2>
              <button type="button" className="icon-button" aria-label="关闭扫码登录窗口" autoFocus onClick={() => setShowQrModal(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="modal-body" style={{ textAlign: "center" }}>
              {ilinkQr?.qrcode ? (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
                  <img
                    src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(ilinkQr.qrcode)}`}
                    alt="微信通道登录二维码"
                    style={{ width: 200, height: 200, borderRadius: 12, border: "1px solid var(--border-card)" }}
                  />
                  <p style={{ fontSize: 13, color: "var(--text-muted)" }}>请使用手机微信扫码并确认登录</p>
                </div>
              ) : (
                <div style={{ padding: 30, color: "var(--text-muted)" }}>
                  正在生成登录凭据...
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="ghost-button"
                onClick={() => void pollIlinkLogin()}
              >
                检查登录状态
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ==========================================================================
   View: 扩展与技能 (Extensions)
   ========================================================================== */

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
  togglePlugin: (name: string, enabled: boolean) => Promise<void>;
  toggleSkill: (name: string, enabled: boolean) => Promise<void>;
  reloadPlugins: () => Promise<void>;
  reloadSkills: () => Promise<void>;
}) {
  const [tab, setTab] = useState<"plugins" | "skills">("plugins");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div className="extensions-toolbar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className={tab === "plugins" ? "primary-button" : "ghost-button"}
            onClick={() => setTab("plugins")}
          >
            本机插件
          </button>
          <button
            type="button"
            className={tab === "skills" ? "primary-button" : "ghost-button"}
            onClick={() => setTab("skills")}
          >
            本机技能
          </button>
        </div>

        <button
          type="button"
          className="ghost-button"
          onClick={() => (tab === "plugins" ? void reloadPlugins() : void reloadSkills())}
        >
          <RefreshCw size={14} /> 热重载
        </button>
      </div>

      <h3>本机已安装（{tab==='plugins'?plugins.length:skills.length}）</h3><div className="extensions-grid">
        {tab === "plugins" ? (
          plugins.map((p) => (
            <div key={p.name} className="extension-card">
              <div className="extension-card__head">
                <div className="extension-icon-wrap">
                  <Package size={22} />
                </div>
                <span className={`status-pill ${p.enabled ? "status-pill--ok" : "status-pill--neutral"}`}>
                  {p.enabled ? "已启用" : "已禁用"}
                </span>
              </div>

              <div>
                <h3 style={{ margin: "0 0 4px 0", fontSize: 15, fontWeight: 700 }}>
                  {p.name} <small style={{ fontWeight: "normal", color: "var(--text-light)", fontSize: 12 }}>v{p.version}</small>
                </h3>
                <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                  {p.description ? wechatChannelDisplayText(p.description) : "暂无插件描述"}
                </p>
              </div>

              <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 12 }}>
                <button
                  type="button"
                  className={`ghost-button ${p.enabled ? "danger" : ""}`}
                  style={{ width: "100%", fontSize: 12 }}
                  onClick={() => void togglePlugin(p.name, p.enabled)}
                >
                  {p.enabled ? "禁用插件" : "启用插件"}
                </button>
              </div>
            </div>
          ))
        ) : (
          skills.map((s) => (
            <div key={s.name} className="extension-card">
              <div className="extension-card__head">
                <div className="extension-icon-wrap" style={{ background: "var(--accent-purple-soft)", color: "var(--accent-purple)" }}>
                  <Zap size={22} />
                </div>
                <span className={`status-pill ${s.enabled ? "status-pill--ok" : "status-pill--neutral"}`}>
                  {s.enabled ? "已加载" : "未加载"}
                </span>
              </div>

              <div>
                <h3 style={{ margin: "0 0 4px 0", fontSize: 15, fontWeight: 700 }}>
                  {s.name}
                </h3>
                <p style={{ margin: "0 0 8px 0", fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                  {s.description || "暂无技能描述"}
                </p>
                {s.tools && s.tools.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {s.tools.map((t) => (
                      <span key={t} className="profile-tag" style={{ fontSize: 10.5 }}>
                        🔧 {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 12 }}>
                <button
                  type="button"
                  className={`ghost-button ${s.enabled ? "danger" : ""}`}
                  style={{ width: "100%", fontSize: 12 }}
                  onClick={() => void toggleSkill(s.name, s.enabled)}
                >
                  {s.enabled ? "卸载技能" : "启用技能"}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ==========================================================================
   View: 控制台设置 (SettingsView)
   ========================================================================== */

function SettingsView({
  onChat,
  status,
  themeMode,
  setThemeMode,
  onConfigApplied,
}: {
  onChat: () => void;
  status: SystemStatus | null;
  themeMode: ThemeMode;
  setThemeMode: (t: ThemeMode) => void;
  onConfigApplied: (event: ConfigAppliedEvent) => Promise<void>;
}) {
  return (
    <SettingsHome onChat={onChat} onApplied={onConfigApplied}>
        <div className="settings-appearance-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
          <div className="card">
            <h2 className="card__title">主题</h2>
            <div className="settings-theme-options">
              <button
                type="button"
                className={themeMode === "light" ? "primary-button" : "ghost-button"}
                aria-pressed={themeMode === "light"}
                onClick={() => setThemeMode("light")}
              >
                <Sun size={15} /> 浅色
              </button>
              <button
                type="button"
                className={themeMode === "dark" ? "primary-button" : "ghost-button"}
                aria-pressed={themeMode === "dark"}
                onClick={() => setThemeMode("dark")}
              >
                <Moon size={15} /> 深色
              </button>
              <button
                type="button"
                className={themeMode === "system" ? "primary-button" : "ghost-button"}
                aria-pressed={themeMode === "system"}
                onClick={() => setThemeMode("system")}
              >
                <Monitor size={15} /> 跟随系统
              </button>
            </div>
          </div>

          <div className="card">
            <h2 className="card__title">运行状态</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-muted)" }}>服务名称:</span>
                <b>{status?.name || "xbot-next"}</b>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-muted)" }}>引擎状态:</span>
                <span className={`status-pill status-pill--${status?.engine?.state === "running" ? "ok" : "neutral"}`}>
                  {status?.engine?.state || "未知"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-muted)" }}>存储层:</span>
                <span>{status?.storage || "未知"}</span>
              </div>
            </div>
          </div>
        </div>
        <FrameworkUpdate version={frontendVersion} settings />
    </SettingsHome>
  );
}

/* ==========================================================================
   Modals & Helper Functions
   ========================================================================== */

function ProfileEditModal({
  user,
  onClose,
  onSave,
}: {
  user: WechatUserDetail;
  onClose: () => void;
  onSave: (userId: string, conversationId: string | null, summary: string, tags: string[]) => Promise<WechatUserDetail>;
}) {
  const [tagsText, setTagsText] = useState((user.profile.tags || []).join(", "));
  const [summary, setSummary] = useState(user.profile.summary || "");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      const tags = tagsText.split(/[,，\s]+/).map((t) => t.trim()).filter(Boolean);
      await onSave(user.contact.user_id, null, summary, tags);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="profile-dialog-title" tabIndex={-1} onClick={(e) => e.stopPropagation()} onKeyDown={(event) => trapDialogFocus(event, onClose)}>
        <div className="modal-header">
          <h2 className="modal-title" id="profile-dialog-title">编辑用户画像 · {user.contact.nickname || user.contact.user_id}</h2>
          <button type="button" className="icon-button" aria-label="关闭用户画像窗口" autoFocus onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <label style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-main)", display: "block", marginBottom: 6 }}>
                画像标签 (以逗号分隔)
              </label>
              <input
                type="text"
                className="input-text"
                value={tagsText}
                onChange={(e) => setTagsText(e.target.value)}
                placeholder="例如: 技术极客, 提问活跃, VIP客户..."
              />
            </div>

            <div>
              <label style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-main)", display: "block", marginBottom: 6 }}>
                个性与交互特征描述
              </label>
              <textarea
                className="input-text"
                rows={4}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="输入或修改针对该用户的长期画像分析与记忆摘要..."
              />
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button type="button" className="ghost-button" onClick={onClose}>
            取消
          </button>
          <button type="button" className="primary-button" onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : "保存画像"}
          </button>
        </div>
      </div>
    </div>
  );
}

function trapDialogFocus(event: ReactKeyboardEvent<HTMLDivElement>, onClose?: () => void) {
  if (event.key === "Escape" && onClose) {
    event.preventDefault();
    onClose();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
    "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
  )).filter((element) => !element.hasAttribute("hidden"));
  if (focusable.length === 0) {
    event.preventDefault();
    event.currentTarget.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function formatTimeShort(value?: string | null): string {
  if (!value) return "";
  try {
    const d = new Date(value.endsWith("Z") ? value : `${value}Z`);
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return value;
  }
}

function channelDisplayName(name: string): string {
  const map: Record<string, string> = {
    wechat_ilink: "微信 iLink 官方网关",
    wechat869: WECHAT_CLIENT_LABEL,
    qq: "QQ 开放平台网关",
    web: "Web 网页交互通道",
    telegram: "Telegram Bot 网关",
  };
  return map[name] || name;
}

function sortWechatMessages(items: WechatMessage[]): WechatMessage[] {
  return [...items].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
}

class PageErrorBoundary extends Component<{ resetKey: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prevProps: { resetKey: string }) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 30, textAlign: "center" }}>
          <div className="error-banner">页面渲染异常: {this.state.error.message}</div>
          <button
            type="button"
            className="primary-button"
            style={{ marginTop: 16 }}
            onClick={() => this.setState({ error: null })}
          >
            重试恢复
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
