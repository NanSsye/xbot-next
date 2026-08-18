import type {
  AdapterInfo,
  AdapterStatus,
  AgentEvent,
  AgentMemoryInfo,
  AgentTask,
  AgentTaskDetail,
  AgentToolInfo,
  ApiEnvelope,
  BackgroundTask,
  ConfigApplyResult,
  ConfigChange,
  ConfigSnapshot,
  Conversation,
  Message,
  PluginInfo,
  ScheduledJob,
  SkillInfo,
  SystemStatus,
  IlinkQrCode,
  WechatConversation,
  WechatGroupPersona,
  WechatMember,
  WechatMessage,
  WechatUserDetail,
  WechatProfilePage,
  CommunityConfig,
  CommunityOverview,
  CommunityUser,
  CommunityLedgerEntry,
  KnowledgeBase,
  KnowledgePage,
  KnowledgeRun,
  LlmModelDiscovery,
} from "./types";

const API_BASE = import.meta.env.VITE_XBOT_API_BASE ?? "/api/v1";
const TOKEN_STORAGE_KEY = "xbot.api.token";

export function apiBase(): string {
  return API_BASE;
}

export function getApiToken(): string {
  return window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
}

export function setApiToken(token: string): void {
  const next = token.trim();
  if (next) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, next);
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function clearApiToken(): void {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getApiToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(!(init?.body instanceof FormData) ? { "content-type": "application/json" } : {}),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401) {
      throw new Error("unauthorized: 请填写 xbot API Token");
    }
    let detail = text;
    try {
      const payload = JSON.parse(text) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
      if (Array.isArray(payload.detail)) {
        detail = payload.detail
          .map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item))
          .join("；");
      }
    } catch {
      // Keep plain-text responses as-is.
    }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  const envelope = (await response.json()) as ApiEnvelope<T>;
  return envelope.data;
}

export const api = {
  status: () => request<SystemStatus>("/system/status"),
  adapters: () => request<AdapterInfo[]>("/adapters"),
  enableAdapter: (name: string) => request<AdapterInfo[]>(`/adapters/${encodeURIComponent(name)}/enable`, { method: "POST" }),
  disableAdapter: (name: string) => request<AdapterInfo[]>(`/adapters/${encodeURIComponent(name)}/disable`, { method: "POST" }),
  adapterStatus: (name: string) => request<AdapterStatus>(`/adapters/${encodeURIComponent(name)}/status`),
  wechatIlinkQrcode: () => request<IlinkQrCode>("/adapters/wechat_ilink/login/qrcode", { method: "POST" }),
  wechatIlinkLoginStatus: (qrcode?: string) => {
    const query = qrcode ? `?qrcode=${encodeURIComponent(qrcode)}` : "";
    return request<AdapterStatus>(`/adapters/wechat_ilink/login/status${query}`);
  },
  wechat869LoginStart: (payload?: { device_type?: string; proxy?: string }) =>
    request<AdapterStatus>("/adapters/wechat869/login/start", {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    }),
  wechat869LoginStatus: () => request<AdapterStatus>("/adapters/wechat869/login/status"),
  plugins: () => request<PluginInfo[]>("/plugins"),
  reloadPlugins: () => request<PluginInfo[]>("/plugins/reload", { method: "POST" }),
  enablePlugin: (name: string) => request(`/plugins/${encodeURIComponent(name)}/enable`, { method: "POST" }),
  disablePlugin: (name: string) => request(`/plugins/${encodeURIComponent(name)}/disable`, { method: "POST" }),
  skills: () => request<SkillInfo[]>("/skills"),
  reloadSkills: () => request<SkillInfo[]>("/skills/reload", { method: "POST" }),
  enableSkill: (name: string) => request(`/skills/${encodeURIComponent(name)}/enable`, { method: "POST" }),
  disableSkill: (name: string) => request(`/skills/${encodeURIComponent(name)}/disable`, { method: "POST" }),
  conversations: (limit = 100) => request<Conversation[]>(`/conversations?limit=${limit}`),
  messages: (conversationId: string, limit = 80) =>
    request<Message[]>(`/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`),
  wechatConversations: (limit = 100) => request<WechatConversation[]>(`/wechat/conversations?limit=${limit}`),
  wechatMessages: (conversationId: string, limit = 200) =>
    request<WechatMessage[]>(`/wechat/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`),
  wechatMembers: (conversationId: string) =>
    request<WechatMember[]>(`/wechat/conversations/${encodeURIComponent(conversationId)}/members`),
  wechatGroupPersona: (conversationId: string) =>
    request<WechatGroupPersona>(`/wechat/conversations/${encodeURIComponent(conversationId)}/persona`),
  updateWechatGroupPersona: (conversationId: string, payload: { enabled: boolean; prompt: string; model?: string | null }) =>
    request<WechatGroupPersona>(`/wechat/conversations/${encodeURIComponent(conversationId)}/persona`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  resetWechatGroupPersonaSession: (conversationId: string) =>
    request<Record<string, unknown>>(`/wechat/conversations/${encodeURIComponent(conversationId)}/persona/reset-session`, { method: "POST" }),
  wechatProfilePage: (conversationId: string, limit = 30, cursor = "") =>
    request<WechatProfilePage>(`/wechat/conversations/${encodeURIComponent(conversationId)}/profiles?limit=${limit}&cursor=${encodeURIComponent(cursor)}`),
  wechatUsers: (limit = 500, q = "") =>
    request<WechatUserDetail[]>(`/wechat/users?limit=${limit}&q=${encodeURIComponent(q)}`),
  wechatUser: (userId: string, conversationId?: string) => {
    const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
    return request<WechatUserDetail>(`/wechat/users/${encodeURIComponent(userId)}${query}`);
  },
  updateWechatProfile: (userId: string, payload: { conversation_id?: string | null; summary: string; tags: string[] }) =>
    request<WechatUserDetail>(`/wechat/users/${encodeURIComponent(userId)}/profile`, { method: "PUT", body: JSON.stringify(payload) }),
  sendWechatMessage: (conversationId: string, payload: { text?: string; file?: File | null }) => {
    const form = new FormData();
    form.set("text", payload.text ?? "");
    if (payload.file) form.set("file", payload.file);
    return request<WechatMessage>(`/wechat/conversations/${encodeURIComponent(conversationId)}/send`, { method: "POST", body: form });
  },
  syncWechatMetadata: () => request<Record<string, number>>("/wechat/sync", { method: "POST" }),
  deleteConversation: (conversationId: string) =>
    request(`/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" }),
  sendAgentTask: (input: string, source: string) =>
    request<AgentTask>("/agent/tasks", {
      method: "POST",
      body: JSON.stringify({ input, source }),
    }),
  agentTasks: (limit = 50) => request<AgentTask[]>(`/agent/tasks?limit=${limit}`),
  agentTaskDetail: (taskId: string) => request<AgentTaskDetail>(`/agent/tasks/${encodeURIComponent(taskId)}`),
  continueAgentTask: (taskId: string, input: string, source = "terminal:control-ui") =>
    request<AgentTask>(`/agent/tasks/${encodeURIComponent(taskId)}/continue`, {
      method: "POST",
      body: JSON.stringify({ input, source }),
    }),
  resumeAgentTask: (taskId: string) =>
    request<AgentTask>(`/agent/tasks/${encodeURIComponent(taskId)}/resume`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  tools: () => request<AgentToolInfo[]>("/agent/tools"),
  llmStatus: () => request<Record<string, unknown>>("/agent/llm/status"),
  mcpStatus: () => request<Record<string, unknown>>("/agent/mcp/status"),
  reloadMcp: () => request<Record<string, unknown>>("/agent/mcp/reload", { method: "POST" }),
  memories: (limit = 50) => request<AgentMemoryInfo[]>(`/agent/memories?limit=${limit}`),
  createMemory: (kind: string, summary: string) =>
    request<AgentMemoryInfo>("/agent/memories", {
      method: "POST",
      body: JSON.stringify({ kind, summary }),
    }),
  deleteMemory: (memoryId: string) => request(`/agent/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" }),
  compactMemories: () => request<AgentMemoryInfo>("/agent/memories/compact", { method: "POST" }),
  agentEvents: (limit = 100, taskId?: string) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (taskId) query.set("task_id", taskId);
    return request<AgentEvent[]>(`/agent/events?${query.toString()}`);
  },
  backgroundTasks: (limit = 50) => request<BackgroundTask[]>(`/agent/background-tasks?limit=${limit}`),
  replayBackgroundTask: (taskId: string) =>
    request<BackgroundTask>(`/agent/background-tasks/${encodeURIComponent(taskId)}/replay`, { method: "POST" }),
  cancelBackgroundTask: (taskId: string) =>
    request<BackgroundTask>(`/agent/background-tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" }),
  scheduledJobs: (limit = 100) => request<ScheduledJob[]>(`/agent/scheduled-jobs?limit=${limit}&include_disabled=true`),
  config: () => request<ConfigSnapshot>("/config"),
  discoverLlmModels: () => request<LlmModelDiscovery>("/config/llm/models/discover", { method: "POST" }),
  updateConfig: (payload: { revision?: string | null; changes: ConfigChange[] }) =>
    request<ConfigApplyResult>("/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  createScheduledJob: (payload: {
    input: string;
    schedule: string;
    name?: string;
    source?: string;
    reply_policy?: string;
    max_runs?: number | null;
    timezone?: string;
  }) =>
    request<ScheduledJob>("/agent/scheduled-jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  pauseScheduledJob: (jobId: string) =>
    request<ScheduledJob>(`/agent/scheduled-jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST" }),
  resumeScheduledJob: (jobId: string) =>
    request<ScheduledJob>(`/agent/scheduled-jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" }),
  runScheduledJob: (jobId: string) =>
    request<ScheduledJob>(`/agent/scheduled-jobs/${encodeURIComponent(jobId)}/run`, { method: "POST" }),
  deleteScheduledJob: (jobId: string) =>
    request(`/agent/scheduled-jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
  communityConfig: () => request<CommunityConfig>("/community/config"),
  updateCommunityConfig: (payload: CommunityConfig) =>
    request<CommunityConfig>("/community/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  communityOverview: () => request<CommunityOverview>("/community/overview"),
  communityUsers: (limit = 300) => request<CommunityUser[]>(`/community/users?limit=${limit}`),
  communityLedger: (limit = 300) => request<CommunityLedgerEntry[]>(`/community/ledger?limit=${limit}`),
  unbindCommunityIdentity: (identityId: number) =>
    request(`/community/identities/${identityId}`, { method: "DELETE" }),
  freezeCommunityAccount: (accountId: number, frozen: boolean) =>
    request(`/community/accounts/${accountId}/freeze`, {
      method: "PUT",
      body: JSON.stringify({ frozen }),
    }),
  adjustCommunityPoints: (accountId: number, delta: number, reason: string) =>
    request<{ applied: number; balance: number }>(`/community/accounts/${accountId}/points`, {
      method: "POST",
      body: JSON.stringify({ delta, reason }),
    }),
  knowledgeBases: () => request<KnowledgeBase[]>("/knowledge/bases"),
  knowledgeBase: (conversationId: string) =>
    request<KnowledgeBase>(`/knowledge/bases/${encodeURIComponent(conversationId)}`),
  updateKnowledgeBase: (conversationId: string, enabled: boolean) =>
    request<KnowledgeBase>(`/knowledge/bases/${encodeURIComponent(conversationId)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  runKnowledgeBase: (conversationId: string) =>
    request<{ conversation_id: string; started: boolean }>(`/knowledge/bases/${encodeURIComponent(conversationId)}/run`, { method: "POST" }),
  knowledgePages: (conversationId: string, q = "") =>
    request<KnowledgePage[]>(`/knowledge/bases/${encodeURIComponent(conversationId)}/pages?q=${encodeURIComponent(q)}&limit=500`),
  knowledgePage: (conversationId: string, path: string) =>
    request<{ conversation_id: string; relative_path: string; content: string }>(`/knowledge/bases/${encodeURIComponent(conversationId)}/page?path=${encodeURIComponent(path)}`),
  knowledgeRuns: (conversationId: string) =>
    request<KnowledgeRun[]>(`/knowledge/bases/${encodeURIComponent(conversationId)}/runs?limit=30`),
  downloadKnowledgeVault: async (conversationId: string) => {
    const token = getApiToken();
    const response = await fetch(`${API_BASE}/knowledge/bases/${encodeURIComponent(conversationId)}/download`, {
      headers: token ? { authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error(await response.text() || "下载 Vault 失败");
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "xbot-group-vault.zip";
    anchor.click();
    URL.revokeObjectURL(url);
  },
};

export function wsUrl(): string {
  const configured = import.meta.env.VITE_XBOT_WS_URL as string | undefined;
  const token = getApiToken();
  if (configured) return withWsToken(configured, token);
  const base = API_BASE.replace(/^http/, "ws").replace(/\/$/, "");
  if (base.startsWith("/")) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return withWsToken(`${protocol}//${window.location.host}${base}/events/ws`, token);
  }
  return withWsToken(`${base}/events/ws`, token);
}

function withWsToken(url: string, token: string): string {
  if (!token) return url;
  const next = new URL(url, window.location.href);
  next.searchParams.set("token", token);
  return next.toString();
}
