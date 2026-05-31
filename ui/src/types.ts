export type ApiEnvelope<T> = {
  success: boolean;
  data: T;
};

export type RuntimeStatus = {
  state: string;
  plugin_count: number;
  skill_count: number;
  adapter_count: number;
  started_at?: string;
};

export type SystemStatus = {
  name: string;
  debug: boolean;
  storage: string;
  engine: RuntimeStatus;
};

export type AdapterInfo = {
  name: string;
  platform: string;
  enabled: boolean;
  configured_enabled?: boolean;
  persistent_enabled?: boolean | null;
  effective_enabled?: boolean;
  started?: boolean;
  status?: string;
};

export type PluginInfo = {
  name: string;
  version: string;
  description: string;
  enabled: boolean;
};

export type SkillInfo = {
  name: string;
  version: string;
  description: string;
  tools: string[];
  enabled: boolean;
  path?: string;
};

export type Conversation = {
  id: string;
  platform: string;
  adapter: string;
  scope: string;
  raw_id: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  platform: string;
  adapter: string;
  conversation_id: string;
  sender_id: string;
  sender_name?: string | null;
  type: string;
  content?: string | null;
  raw?: Record<string, unknown>;
  timestamp: string;
};

export type AgentTask = {
  task_id: string;
  source: string;
  status: string;
  output: string;
  created_at: string;
  suppress_channel_reply?: boolean;
};

export type AgentEvent = {
  id?: number;
  task_id: string;
  type: string;
  content: unknown;
  created_at: string;
};

export type BackgroundTask = {
  id: string;
  kind: string;
  status: string;
  source: string;
  description: string;
  progress?: string;
  result?: unknown;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  metadata?: Record<string, unknown>;
};

export type ScheduledJob = {
  id: string;
  name: string;
  enabled: boolean;
  schedule_type: string;
  schedule_display: string;
  timezone: string;
  input: string;
  source: string;
  reply_policy: string;
  run_count: number;
  max_runs?: number | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  last_task_id?: string | null;
  last_error?: string | null;
};

export type UiEvent = {
  id: string;
  type: string;
  topic: string;
  data: unknown;
  created_at: string;
};

export type AgentToolInfo = {
  name: string;
  description: string;
  risk_level: string;
  toolset?: string;
  source?: string;
  cacheable?: boolean;
  timeout_seconds?: number | null;
  metadata?: Record<string, unknown>;
};

export type AgentMemoryInfo = {
  id: string;
  kind: string;
  summary: string;
  created_at: string;
};
