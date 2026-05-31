import type {
  AdapterInfo,
  AgentEvent,
  AgentMemoryInfo,
  AgentTask,
  AgentToolInfo,
  ApiEnvelope,
  BackgroundTask,
  Conversation,
  Message,
  PluginInfo,
  ScheduledJob,
  SkillInfo,
  SystemStatus,
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
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401) {
      throw new Error("unauthorized: 请填写 xbot API Token");
    }
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  const envelope = (await response.json()) as ApiEnvelope<T>;
  return envelope.data;
}

export const api = {
  status: () => request<SystemStatus>("/system/status"),
  adapters: () => request<AdapterInfo[]>("/adapters"),
  enableAdapter: (name: string) => request<AdapterInfo[]>(`/adapters/${encodeURIComponent(name)}/enable`, { method: "POST" }),
  disableAdapter: (name: string) => request<AdapterInfo[]>(`/adapters/${encodeURIComponent(name)}/disable`, { method: "POST" }),
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
  deleteConversation: (conversationId: string) =>
    request(`/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" }),
  sendAgentTask: (input: string, source: string) =>
    request<AgentTask>("/agent/tasks", {
      method: "POST",
      body: JSON.stringify({ input, source }),
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
