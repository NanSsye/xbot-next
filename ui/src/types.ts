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

export type AdapterStatus = Record<string, unknown> & {
  adapter?: string;
  platform?: string;
  started?: boolean;
  logged_in?: boolean;
  login_supported?: boolean;
};

export type IlinkQrCode = {
  qrcode: string;
  qr_url: string;
  base_url: string;
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
  avatar_url?: string | null;
  avatar_members?: string[];
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
  id?: string;
  task_id: string;
  source: string;
  status: string;
  input?: string;
  output: string;
  result?: string | null;
  created_at: string;
  updated_at?: string;
  suppress_channel_reply?: boolean;
};

export type AgentEvent = {
  id?: number;
  task_id: string;
  type: string;
  content: unknown;
  created_at: string;
};

export type AgentTaskTimelineItem = {
  type: string;
  title: string;
  status: string;
  content: unknown;
  created_at: string;
};

export type AgentTaskToolCall = {
  tool: string;
  status: string;
  risk_level?: string;
  input?: unknown;
  output?: unknown;
  error?: string | null;
  fallback?: Record<string, unknown> | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type AgentTaskRepair = {
  tool?: string;
  error?: string;
  error_type?: string;
  guidance?: string;
  repair_steps?: string[];
  suggested_tool?: string | null;
  suggested_payload?: unknown;
  auto_result?: unknown;
  created_at?: string;
};

export type AgentArtifact = {
  id: string;
  task_id: string;
  kind: string;
  path: string;
  content_hash?: string | null;
  summary?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
};

export type AgentTaskDetail = {
  task: AgentTask;
  events: AgentEvent[];
  timeline: AgentTaskTimelineItem[];
  tool_calls: AgentTaskToolCall[];
  repairs: AgentTaskRepair[];
  artifacts: AgentArtifact[];
  summary: Record<string, number>;
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


export type WechatAttachment = {
  id: number;
  message_id: string;
  conversation_id: string;
  sender_id: string;
  kind: string;
  filename?: string | null;
  mime?: string | null;
  size: number;
  local_path?: string | null;
  url?: string | null;
  sha256?: string | null;
  download_status: string;
  quoted: boolean;
  metadata?: Record<string, unknown>;
  created_at: string;
};

export type WechatMessage = Message & {
  attachments: WechatAttachment[];
  sender_avatar_url?: string | null;
};

export type WechatConversation = Conversation & {
  message_count: number;
  avatar_members?: string[];
  last_message?: WechatMessage | null;
};

export type WechatMember = {
  user_id: string;
  nickname: string;
  remark?: string | null;
  avatar_url?: string | null;
  conversation_id?: string;
  message_count: number;
  last_active_at?: string | null;
};

export type WechatUserDetail = {
  contact: {
    user_id: string;
    nickname: string;
    remark?: string | null;
    avatar_url?: string | null;
  };
  stats: { message_count: number; image_count: number };
  profile: { summary: string; tags: string[]; updated_at?: string | null };
  recent_messages: WechatMessage[];
  images: WechatAttachment[];
};

export type WechatProfilePage = {
  items: Array<WechatUserDetail & { last_active_at?: string | null }>;
  total: number;
  next_cursor?: string | null;
};
