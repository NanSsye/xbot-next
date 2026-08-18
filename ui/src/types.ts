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

export type ConfigFieldType = "boolean" | "integer" | "number" | "list" | "json" | "string";

export type ConfigField = {
  path: string;
  key: string;
  label: string;
  description: string;
  type: ConfigFieldType;
  value: unknown;
  configured: boolean;
  masked_value: string;
  secret: boolean;
  source: "web" | "env_or_file";
  overridden: boolean;
  env_name: string;
  options: string[];
  restart_required: boolean;
  pending_restart: boolean;
  adapter_toggle: boolean;
};

export type ConfigSection = {
  key: string;
  title: string;
  description: string;
  scope: "system" | "channels";
  fields: ConfigField[];
};

export type ConfigSnapshot = {
  revision: string;
  runtime_file: string;
  sections: ConfigSection[];
  pending_restart: string[];
  updated_at?: string | null;
};

export type ConfigChange = {
  path: string;
  value?: unknown;
  reset?: boolean;
};

export type ConfigApplyResult = {
  applied: string[];
  restart_required: string[];
  snapshot: ConfigSnapshot;
};

export type LlmModelDiscovery = {
  models: string[];
  count: number;
};

export type WechatConversation = Conversation & {
  message_count: number;
  avatar_members?: string[];
  last_message?: WechatMessage | null;
};

export type WechatGroupPersona = {
  conversation_id: string;
  enabled: boolean;
  prompt: string;
  model?: string | null;
  default_model: string;
  enabled_models: string[];
  updated_at?: string | null;
};

export type KnowledgeBase = {
  conversation_id: string;
  title: string;
  platform: string;
  adapter: string;
  enabled: boolean;
  interval_seconds: number;
  cursor_record_id: number;
  status: "idle" | "running" | "failed" | string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
  page_count: number;
  source_count: number;
  file_count: number;
  person_count: number;
  updated_at: string;
};

export type KnowledgePage = {
  id: number;
  conversation_id: string;
  relative_path: string;
  title: string;
  summary: string;
  tags: string[];
  source_ids: string[];
  updated_at: string;
};

export type KnowledgeRun = {
  id: string;
  conversation_id: string;
  status: string;
  from_cursor: number;
  to_cursor: number;
  message_count: number;
  file_count: number;
  page_change_count: number;
  model?: string | null;
  input_tokens: number;
  output_tokens: number;
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
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

export type CommunityConfig = {
  enabled: boolean;
  enabled_adapters: string[];
  allowed_conversation_ids: string[];
  red_packet_admin_user_ids: string[];
  require_mention: boolean;
  timezone: string;
  checkin_base_reward: number;
  checkin_streak_3_bonus: number;
  checkin_streak_7_bonus: number;
  checkin_streak_30_bonus: number;
  activity_enabled: boolean;
  activity_rewards: number[];
  activity_min_messages: number;
  activity_settle_hour: number;
  activity_settle_minute: number;
  activity_announce: boolean;
  activity_milestone_enabled: boolean;
  activity_milestone_messages: number;
  activity_milestone_reward: number;
  rps_daily_limit: number;
  rps_win_reward: number;
  rps_draw_reward: number;
  fortune_min_reward: number;
  fortune_max_reward: number;
  treasure_enabled: boolean;
  treasure_min_reward: number;
  treasure_max_reward: number;
  boss_enabled: boolean;
  boss_daily_hp: number;
  boss_daily_attacks: number;
  boss_min_damage: number;
  boss_max_damage: number;
  boss_min_reward: number;
  boss_max_reward: number;
  boss_kill_reward_pool: number;
  horse_race_enabled: boolean;
  horse_race_start_hour: number;
  horse_race_end_hour: number;
  horse_race_interval_hours: number;
  horse_race_draw_minute: number;
  horse_race_prize_pool: number;
  high_low_enabled: boolean;
  high_low_stake: number;
  high_low_daily_limit: number;
  leaderboard_enabled: boolean;
  token_exchange_enabled: boolean;
  token_exchange_points: number;
  token_exchange_tokens: number;
  created_at?: string;
  updated_at?: string;
};

export type CommunityOverview = {
  accounts: number;
  identities: number;
  points: number;
  checkins_today: number;
};

export type CommunityUser = {
  identity_id: number;
  account_id: number;
  platform: string;
  adapter: string;
  user_id: string;
  nickname?: string | null;
  last_conversation_id?: string | null;
  points_balance: number;
  frozen: boolean;
  bound_at: string;
  last_seen_at: string;
};

export type CommunityLedgerEntry = {
  id: number;
  account_id: number;
  nickname: string;
  delta: number;
  balance_after: number;
  reason: string;
  conversation_id?: string | null;
  effective_date: string;
  created_at: string;
};
