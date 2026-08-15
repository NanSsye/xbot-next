import {
  Check,
  Coins,
  Gamepad2,
  History,
  Medal,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  UserRoundCheck,
  Users,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  CommunityConfig,
  CommunityLedgerEntry,
  CommunityOverview,
  CommunityUser,
} from "../types";

type Tab = "overview" | "config" | "users" | "ledger";

const adapterOptions = [
  { value: "qq", label: "QQ" },
  { value: "wechat869", label: "微信 869" },
  { value: "wechat_ilink", label: "微信 iLink" },
];

const reasonLabels: Record<string, string> = {
  checkin: "每日签到",
  daily_activity_rank: "群发言榜",
  daily_activity_milestone: "每日发言奖励",
  game_rps_win: "猜拳胜利",
  game_rps_draw: "猜拳平局",
  game_rps_lose: "猜拳参与",
  game_fortune: "每日运势",
  game_treasure: "幸运宝箱",
  game_boss_attack: "每日 Boss 攻击",
  game_boss_kill: "每日 Boss 击杀奖励",
  game_horse_race: "群体赛马奖励",
  game_high_low_stake: "押大小投入",
  game_high_low_payout: "押大小返奖",
  admin_adjustment: "管理员调整",
  token_exchange: "Token 加油包",
  token_exchange_refund: "Token 兑换退回",
};

export function CommunityCenter() {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<CommunityOverview | null>(null);
  const [config, setConfig] = useState<CommunityConfig | null>(null);
  const [users, setUsers] = useState<CommunityUser[]>([]);
  const [ledger, setLedger] = useState<CommunityLedgerEntry[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [adjusting, setAdjusting] = useState<CommunityUser | null>(null);
  const [adjustDelta, setAdjustDelta] = useState("");
  const [adjustReason, setAdjustReason] = useState("");

  const load = useCallback(async () => {
    setBusy("load");
    setError("");
    try {
      const [nextOverview, nextConfig, nextUsers, nextLedger] = await Promise.all([
        api.communityOverview(),
        api.communityConfig(),
        api.communityUsers(),
        api.communityLedger(),
      ]);
      setOverview(nextOverview);
      setConfig(nextConfig);
      setUsers(nextUsers);
      setLedger(nextLedger);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy("");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredUsers = useMemo(() => {
    const value = query.trim().toLowerCase();
    if (!value) return users;
    return users.filter((user) =>
      [user.nickname, user.adapter, user.user_id, user.last_conversation_id]
        .filter(Boolean)
        .some((item) => String(item).toLowerCase().includes(value)),
    );
  }, [query, users]);

  async function saveConfig() {
    if (!config) return;
    setBusy("config");
    setError("");
    setNotice("");
    try {
      await api.updateCommunityConfig(config);
      setConfig(await api.communityConfig());
      setNotice("配置已保存，插件已热加载生效。记录中的日期按新时区从下一条消息起计算。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy("");
    }
  }

  async function toggleFrozen(user: CommunityUser) {
    setBusy(`freeze-${user.account_id}`);
    setError("");
    try {
      await api.freezeCommunityAccount(user.account_id, !user.frozen);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy("");
    }
  }

  async function unbind(user: CommunityUser) {
    if (!window.confirm(`解除“${user.nickname || "未命名用户"}”的当前通道绑定？积分账号和流水会保留。`)) return;
    setBusy(`unbind-${user.identity_id}`);
    setError("");
    try {
      await api.unbindCommunityIdentity(user.identity_id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy("");
    }
  }

  async function submitAdjustment() {
    const delta = Number(adjustDelta);
    if (!adjusting || !Number.isInteger(delta) || delta === 0 || !adjustReason.trim()) {
      setError("请填写非零整数积分和调整原因。");
      return;
    }
    setBusy("adjust");
    setError("");
    try {
      const result = await api.adjustCommunityPoints(adjusting.account_id, delta, adjustReason.trim());
      setNotice(`积分已调整 ${result.applied > 0 ? "+" : ""}${result.applied}，当前余额 ${result.balance}。`);
      setAdjusting(null);
      setAdjustDelta("");
      setAdjustReason("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy("");
    }
  }

  return (
    <section className="community-shell">
      <header className="community-header">
        <div>
          <h2>微伴社区</h2>
          <p>QQ群绑定、积分激励和娱乐玩法统一运营，配置保存后实时生效。</p>
        </div>
        <div className="community-header__actions">
          <span className={`community-live ${config?.enabled ? "community-live--on" : ""}`}>
            <span />{config?.enabled ? "运行中" : "已停用"}
          </span>
          <button className="ghost-button" onClick={() => void load()} disabled={busy === "load"}>
            <RefreshCw size={14} /> 刷新
          </button>
        </div>
      </header>

      <nav className="community-tabs" aria-label="微伴社区管理">
        {([
          ["overview", "运营概览", Medal],
          ["config", "玩法配置", Gamepad2],
          ["users", "绑定用户", Users],
          ["ledger", "积分流水", History],
        ] as const).map(([id, label, Icon]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </nav>

      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <div className="community-notice"><Check size={15} />{notice}</div> : null}

      <div className="community-body">
        {tab === "overview" ? <OverviewPanel data={overview} config={config} users={users} /> : null}
        {tab === "config" && config ? (
          <ConfigPanel config={config} setConfig={setConfig} save={saveConfig} busy={busy === "config"} />
        ) : null}
        {tab === "users" ? (
          <UsersPanel
            users={filteredUsers}
            query={query}
            setQuery={setQuery}
            busy={busy}
            toggleFrozen={toggleFrozen}
            unbind={unbind}
            setAdjusting={setAdjusting}
          />
        ) : null}
        {tab === "ledger" ? <LedgerPanel rows={ledger} /> : null}
      </div>

      {adjusting ? (
        <div className="community-modal-backdrop" role="presentation" onMouseDown={() => setAdjusting(null)}>
          <div className="community-modal" role="dialog" aria-modal="true" aria-labelledby="adjust-title" onMouseDown={(event) => event.stopPropagation()}>
            <h3 id="adjust-title">调整积分</h3>
            <p>{adjusting.nickname || "未命名用户"} · 当前 {adjusting.points_balance} 分</p>
            <label>调整值<input autoFocus type="number" value={adjustDelta} onChange={(event) => setAdjustDelta(event.target.value)} placeholder="正数增加，负数扣减" /></label>
            <label>原因<input value={adjustReason} onChange={(event) => setAdjustReason(event.target.value)} maxLength={256} placeholder="会写入不可变积分流水" /></label>
            <div className="community-modal__actions">
              <button className="ghost-button" onClick={() => setAdjusting(null)}>取消</button>
              <button className="primary-button" onClick={() => void submitAdjustment()} disabled={busy === "adjust"}>{busy === "adjust" ? "提交中…" : "确认调整"}</button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function OverviewPanel({ data, config, users }: { data: CommunityOverview | null; config: CommunityConfig | null; users: CommunityUser[] }) {
  const cards = [
    ["积分账号", data?.accounts ?? 0, Coins],
    ["已绑定身份", data?.identities ?? 0, UserRoundCheck],
    ["当前积分总量", data?.points ?? 0, Medal],
    ["今日签到", data?.checkins_today ?? 0, ShieldCheck],
  ] as const;
  return (
    <div className="community-overview">
      <div className="community-metrics">
        {cards.map(([label, value, Icon]) => <article key={label}><Icon size={18} /><span>{label}</span><strong>{value.toLocaleString()}</strong></article>)}
      </div>
      <div className="community-overview-grid">
        <article className="community-card community-rules">
          <div className="community-card__title"><div><h3>当前生效规则</h3><p>配置来自 PostgreSQL，插件热加载后立即替换运行参数。</p></div></div>
          <dl>
            <div><dt>开放通道</dt><dd>{config?.enabled_adapters.join("、") || "未开放"}</dd></div>
            <div><dt>交互方式</dt><dd>{config?.require_mention ? "群内需要 @小x" : "无需 @"}</dd></div>
            <div><dt>签到基础奖励</dt><dd>{config?.checkin_base_reward ?? 0} 分</dd></div>
            <div><dt>发言榜奖励</dt><dd>{config?.activity_rewards.join(" / ") || "未配置"}</dd></div>
            <div><dt>每日发言奖励</dt><dd>{config?.activity_milestone_enabled ? `${config.activity_milestone_messages} 条 +${config.activity_milestone_reward} 分` : "未开放"}</dd></div>
            <div><dt>Token 加油包</dt><dd>{config?.token_exchange_enabled ? `${config.token_exchange_points} 分 = ${config.token_exchange_tokens.toLocaleString()} Token` : "未开放"}</dd></div>
            <div><dt>结算时间</dt><dd>{String(config?.activity_settle_hour ?? 0).padStart(2, "0")}:{String(config?.activity_settle_minute ?? 0).padStart(2, "0")} · {config?.timezone}</dd></div>
          </dl>
        </article>
        <article className="community-card">
          <div className="community-card__title"><div><h3>最近活跃绑定</h3><p>只显示运营身份，不展示邀请码或微伴账号资料。</p></div></div>
          <div className="community-recent">
            {users.slice(0, 6).map((user) => <div key={user.identity_id}><span className="community-avatar">{(user.nickname || "群").slice(0, 1)}</span><div><strong>{user.nickname || "未命名用户"}</strong><small>{adapterLabel(user.adapter)} · {formatTime(user.last_seen_at)}</small></div><b>{user.points_balance} 分</b></div>)}
            {!users.length ? <div className="empty-state">还没有用户绑定</div> : null}
          </div>
        </article>
      </div>
    </div>
  );
}

function ConfigPanel({ config, setConfig, save, busy }: { config: CommunityConfig; setConfig: (config: CommunityConfig) => void; save: () => void; busy: boolean }) {
  const set = <K extends keyof CommunityConfig>(key: K, value: CommunityConfig[K]) => setConfig({ ...config, [key]: value });
  const number = (key: keyof CommunityConfig, label: string, min = 0, max = 100000) => (
    <label className="community-field"><span>{label}</span><input type="number" min={min} max={max} value={String(config[key])} onChange={(event) => set(key, Number(event.target.value) as never)} /></label>
  );
  return (
    <div className="community-config">
      <div className="community-config__main">
        <ConfigSection title="运行范围" description="控制插件在哪些群和通道响应，默认仅 QQ 群。">
          <Toggle label="启用微伴社区" checked={config.enabled} onChange={(value) => set("enabled", value)} />
          <Toggle label="群命令要求 @机器人" checked={config.require_mention} onChange={(value) => set("require_mention", value)} />
          <div className="community-field community-field--wide"><span>开放通道</span><div className="community-chips">{adapterOptions.map((item) => { const selected = config.enabled_adapters.includes(item.value); return <button key={item.value} type="button" className={selected ? "active" : ""} onClick={() => set("enabled_adapters", selected ? config.enabled_adapters.filter((value) => value !== item.value) : [...config.enabled_adapters, item.value])}>{selected ? <Check size={13} /> : null}{item.label}</button>; })}</div><small>可同时开放多个通道。当前产品默认只启用 QQ。</small></div>
          <label className="community-field community-field--wide"><span>群白名单</span><textarea value={config.allowed_conversation_ids.join("\n")} onChange={(event) => set("allowed_conversation_ids", event.target.value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean))} placeholder="每行一个 conversation_id；留空允许所有群" /><small>填写后只有名单内群聊可使用插件。</small></label>
          <label className="community-field"><span>业务时区</span><input value={config.timezone} onChange={(event) => set("timezone", event.target.value)} /></label>
        </ConfigSection>

        <ConfigSection title="签到与连续奖励" description="连续天数在 3、7、30 的倍数当天叠加对应奖励。">
          {number("checkin_base_reward", "每日签到")}{number("checkin_streak_3_bonus", "连续 3 天加奖")}{number("checkin_streak_7_bonus", "连续 7 天加奖")}{number("checkin_streak_30_bonus", "连续 30 天加奖")}
        </ConfigSection>

        <ConfigSection title="群发言榜" description="只统计已绑定用户的非空文本，按发言数和达成时间排序。">
          <Toggle label="启用每日发言榜" checked={config.activity_enabled} onChange={(value) => set("activity_enabled", value)} />
          <Toggle label="结算后群内公布" checked={config.activity_announce} onChange={(value) => set("activity_announce", value)} />
          <div className="community-field community-field--wide"><span>前五名奖励</span><div className="community-rank-inputs">{config.activity_rewards.map((reward, index) => <label key={index}><small>第 {index + 1} 名</small><input type="number" min="0" value={reward} onChange={(event) => { const rewards = [...config.activity_rewards]; rewards[index] = Number(event.target.value); set("activity_rewards", rewards); }} /></label>)}</div></div>
          {number("activity_min_messages", "最低有效发言数", 1)}{number("activity_settle_hour", "结算小时", 0, 23)}{number("activity_settle_minute", "结算分钟", 0, 59)}
          <Toggle label="启用每日发言达标奖励" checked={config.activity_milestone_enabled} onChange={(value) => set("activity_milestone_enabled", value)} />
          {number("activity_milestone_messages", "每日达标发言数", 1)}
          {number("activity_milestone_reward", "达标奖励积分")}
        </ConfigSection>

        <ConfigSection title="游戏与排行榜" description="有明确每日次数限制的小游戏按配置完整发奖；Boss 击杀积分池不受通用每日上限影响。">
          {number("rps_daily_limit", "猜拳每日次数")}{number("rps_win_reward", "猜拳胜利奖励")}{number("rps_draw_reward", "猜拳平局奖励")}{number("fortune_min_reward", "运势最低奖励")}{number("fortune_max_reward", "运势最高奖励")}
          <Toggle label="开放幸运宝箱" checked={config.treasure_enabled} onChange={(value) => set("treasure_enabled", value)} />
          {number("treasure_min_reward", "宝箱最低奖励")}{number("treasure_max_reward", "宝箱最高奖励")}
          <Toggle label="开放每日 Boss" checked={config.boss_enabled} onChange={(value) => set("boss_enabled", value)} />
          {number("boss_daily_hp", "Boss 每日血量", 1, 10000000)}{number("boss_daily_attacks", "每人每日攻击次数", 1, 1000)}{number("boss_min_damage", "单次最低伤害", 1, 10000)}{number("boss_max_damage", "单次最高伤害", 1, 10000)}{number("boss_min_reward", "单次最低积分", 0, 100000)}{number("boss_max_reward", "单次最高积分", 0, 100000)}{number("boss_kill_reward_pool", "击杀平分积分池", 0, 100000000)}
          <Toggle label="开放群体赛马" checked={config.horse_race_enabled} onChange={(value) => set("horse_race_enabled", value)} />
          {number("horse_race_start_hour", "赛马开始小时", 0, 23)}{number("horse_race_end_hour", "赛马结束小时", 0, 23)}{number("horse_race_interval_hours", "赛马间隔小时", 1, 24)}{number("horse_race_draw_minute", "赛马开奖分钟", 1, 59)}{number("horse_race_prize_pool", "每轮系统奖池", 0, 100000000)}
          <Toggle label="开放押大小" checked={config.high_low_enabled} onChange={(value) => set("high_low_enabled", value)} />
          {number("high_low_stake", "押大小每局投入", 1, 10000)}{number("high_low_daily_limit", "押大小每日次数", 1, 100)}
          <Toggle label="开放积分排行榜" checked={config.leaderboard_enabled} onChange={(value) => set("leaderboard_enabled", value)} />
        </ConfigSection>

        <ConfigSection title="Token 加油包" description="积分兑换进入微伴独立 Token 钱包，不改变会员的 5 小时、周、月额度。">
          <Toggle label="开放积分兑换" checked={config.token_exchange_enabled} onChange={(value) => set("token_exchange_enabled", value)} />
          {number("token_exchange_points", "每份消耗积分", 1, 100000)}
          {number("token_exchange_tokens", "每份到账 Token", 1, 10000000000)}
        </ConfigSection>
      </div>
      <aside className="community-config__aside">
        <h3>生效检查</h3>
        <p>保存会写入 PostgreSQL，并热加载社区插件。</p>
        <ul>
          <li className={config.enabled_adapters.length ? "pass" : "warn"}><Check size={14} />{config.enabled_adapters.length ? `已开放 ${config.enabled_adapters.length} 个通道` : "至少选择一个通道"}</li>
          <li className={config.activity_rewards.length === 5 ? "pass" : "warn"}><Check size={14} />发言榜固定五档奖励</li>
          <li className={config.fortune_max_reward >= config.fortune_min_reward ? "pass" : "warn"}><Check size={14} />运势奖励区间有效</li>
          <li className={config.treasure_max_reward >= config.treasure_min_reward ? "pass" : "warn"}><Check size={14} />宝箱奖励区间有效</li>
          <li className={config.boss_max_damage >= config.boss_min_damage ? "pass" : "warn"}><Check size={14} />Boss 伤害区间有效</li>
          <li className={config.token_exchange_points > 0 && config.token_exchange_tokens > 0 ? "pass" : "warn"}><Check size={14} />Token 兑换比例有效</li>
        </ul>
        <button className="primary-button community-save" onClick={save} disabled={busy || !config.enabled_adapters.length}>{busy ? "保存并加载中…" : <><Save size={15} /> 保存并实时生效</>}</button>
        <small>最后更新：{formatTime(config.updated_at)}</small>
      </aside>
    </div>
  );
}

function ConfigSection({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <section className="community-card community-config-section"><div className="community-card__title"><div><h3>{title}</h3><p>{description}</p></div></div><div className="community-form-grid">{children}</div></section>;
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="community-toggle"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /></label>;
}

function UsersPanel({ users, query, setQuery, busy, toggleFrozen, unbind, setAdjusting }: { users: CommunityUser[]; query: string; setQuery: (value: string) => void; busy: string; toggleFrozen: (user: CommunityUser) => void; unbind: (user: CommunityUser) => void; setAdjusting: (user: CommunityUser) => void }) {
  return <article className="community-card community-table-card"><div className="community-card__title community-card__title--actions"><div><h3>绑定用户</h3><p>点击用户行内“加减积分”，即可给指定用户增加或扣除积分；每次操作都会写入不可变流水。</p></div><label className="compact-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="昵称、通道或群聊" /></label></div><div className="table-wrap"><table><thead><tr><th>用户</th><th>通道</th><th>积分</th><th>状态</th><th>最后活跃</th><th>操作</th></tr></thead><tbody>{users.map((user) => <tr key={user.identity_id}><td><strong>{user.nickname || "未命名用户"}</strong><small className="community-cell-sub">{maskId(user.user_id)}</small></td><td>{adapterLabel(user.adapter)}<small className="community-cell-sub">{shortConversation(user.last_conversation_id)}</small></td><td className="community-points">{user.points_balance}</td><td><span className={`status-pill ${user.frozen ? "status-pill--warn" : "status-pill--ok"}`}>{user.frozen ? "已冻结" : "正常"}</span></td><td>{formatTime(user.last_seen_at)}</td><td><div className="row-actions"><button className="ghost-button" onClick={() => setAdjusting(user)}>加减积分</button><button className="ghost-button" disabled={busy === `freeze-${user.account_id}`} onClick={() => void toggleFrozen(user)}>{user.frozen ? "解冻" : "冻结"}</button><button className="ghost-button danger" disabled={busy === `unbind-${user.identity_id}`} onClick={() => void unbind(user)}>解绑</button></div></td></tr>)}</tbody></table>{!users.length ? <div className="empty-state">没有匹配的绑定用户</div> : null}</div></article>;
}

function LedgerPanel({ rows }: { rows: CommunityLedgerEntry[] }) {
  return <article className="community-card community-table-card"><div className="community-card__title"><div><h3>不可变积分流水</h3><p>每次增减都记录原因、变动后余额和归属日期，网页不可删除。</p></div></div><div className="table-wrap"><table><thead><tr><th>时间</th><th>用户</th><th>原因</th><th>变动</th><th>余额</th><th>群聊</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td>{formatTime(row.created_at)}</td><td>{row.nickname}</td><td>{reasonLabels[row.reason] || row.reason}</td><td className={row.delta > 0 ? "community-delta community-delta--up" : "community-delta community-delta--down"}>{row.delta > 0 ? "+" : ""}{row.delta}</td><td className="community-points">{row.balance_after}</td><td>{shortConversation(row.conversation_id)}</td></tr>)}</tbody></table>{!rows.length ? <div className="empty-state">还没有积分流水</div> : null}</div></article>;
}

function adapterLabel(adapter: string) { return adapterOptions.find((item) => item.value === adapter)?.label || adapter; }
function formatTime(value?: string | null) { return value ? new Date(value.endsWith("Z") ? value : `${value}Z`).toLocaleString("zh-CN", { hour12: false }) : "暂无"; }
function maskId(value: string) { return value.length <= 10 ? value : `${value.slice(0, 5)}…${value.slice(-4)}`; }
function shortConversation(value?: string | null) { if (!value) return "未记录"; const parts = value.split(":"); return parts.length > 2 ? `${parts[0]}:${parts[1]}:${maskId(parts.slice(2).join(":"))}` : maskId(value); }
