import {
  Activity,
  ArrowRight,
  Bot,
  BookOpenText,
  MessagesSquare,
  Network,
  Package,
  Radio,
  RefreshCw,
  Settings,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import type { AdapterInfo, AdapterStatus, AgentToolInfo, PluginInfo, SkillInfo, UiEvent } from "../types";
import { PageHeading } from "./IllustrationHero";
import { WECHAT_CLIENT_LABEL, wechatChannelDisplayText } from "./wechatChannelLabel";
import type { View } from "./App";

export type WebSocketState = "connecting" | "connected" | "disconnected" | "error";

type HomeDashboardProps = {
  adapters: AdapterInfo[];
  adapterStatuses: Record<string, AdapterStatus>;
  plugins: PluginInfo[];
  skills: SkillInfo[];
  tools: AgentToolInfo[];
  wechatConversationCount: number;
  unreadCount: number;
  profileCount: number;
  liveEvents: UiEvent[];
  websocketState: WebSocketState;
  loading: boolean;
  loadErrors: Record<string, string>;
  adapterToggleBusy: string;
  onNavigate: (view: View) => void;
  onRefresh: () => void;
  onToggleAdapter: (name: string, enabled: boolean) => Promise<void>;
};

const websocketLabels: Record<WebSocketState, string> = {
  connecting: "事件流连接中",
  connected: "事件流已连接",
  disconnected: "事件流已断开",
  error: "事件流异常",
};

export function HomeDashboard(props: HomeDashboardProps) {
  const enabledExtensions = props.plugins.filter((item) => item.enabled).length
    + props.skills.filter((item) => item.enabled).length;
  const extensionTotal = props.plugins.length + props.skills.length;
  const degradedCount = Object.keys(props.loadErrors).length;
  const adapterDataUnavailable = Boolean(props.loadErrors.adapters);
  const extensionDataUnavailable = Boolean(props.loadErrors.plugins || props.loadErrors.skills);

  return (
    <div className="content-scroll">
      <PageHeading title="运行概览" tagline="通道、会话与服务状态">
        <div className="home-hero-status" aria-live="polite">
          <span className={`status-pill status-pill--${props.websocketState === "connected" ? "ok" : props.websocketState === "connecting" ? "neutral" : "warn"}`}>
            <span className={`status-dot ${props.websocketState === "connected" ? "status-dot--ok" : "status-dot--warn"}`} />
            {websocketLabels[props.websocketState]}
          </span>
          {degradedCount > 0 ? (
            <span className="status-pill status-pill--warn">{degradedCount} 项数据暂不可用</span>
          ) : (
            <span className="status-pill status-pill--ok">数据读取正常</span>
          )}
        </div>
      </PageHeading>

      <div className="home-dashboard">
        {degradedCount > 0 && (
          <div className="home-data-notice" role="status">
            <div>
              <strong>部分数据加载失败</strong>
              <span>现有数据已保留，失败项不会显示成正常的 0。</span>
            </div>
            <button type="button" className="ghost-button" onClick={props.onRefresh} disabled={props.loading}>
              <RefreshCw size={14} /> 重试
            </button>
          </div>
        )}

        <div className="home-stat-grid" aria-label="核心运行指标">
          <StatButton
            icon={<Network size={22} />}
            tone="coral"
            value={adapterDataUnavailable ? "—" : `${props.adapters.filter((item) => item.started).length} / ${props.adapters.length}`}
            label="在线通道"
            detail={adapterDataUnavailable ? "数据读取失败" : "查看接入与登录状态"}
            onClick={() => props.onNavigate("channels")}
          />
          <StatButton
            icon={<Package size={22} />}
            tone="green"
            value={extensionDataUnavailable ? "—" : `${enabledExtensions} / ${extensionTotal}`}
            label="启用扩展"
            detail="插件与技能合计"
            onClick={() => props.onNavigate("extensions")}
          />
          <StatButton
            icon={<Bot size={22} />}
            tone="purple"
            value={props.loadErrors["agent/tools"] ? "—" : props.tools.length}
            label="Agent 工具"
            detail="查看任务与工具能力"
            onClick={() => props.onNavigate("agentChat")}
          />
          <StatButton
            icon={<MessagesSquare size={22} />}
            tone="blue"
            value={props.loadErrors["wechat/conversations"] ? "—" : props.unreadCount > 0 ? `${props.unreadCount} 未读` : `${props.wechatConversationCount} 会话`}
            label="微信消息"
            detail="进入实时消息工作台"
            onClick={() => props.onNavigate("wechat")}
          />
        </div>

        <div className="home-main-grid">
          <div className="home-column">
            <section className="card" aria-labelledby="home-channel-title">
              <div className="card__header">
                <div>
                  <div className="card__title" id="home-channel-title"><Radio size={18} /><span>通道运行状态</span></div>
                  <div className="card__desc">微信、QQ、Telegram 等协议接入状态</div>
                </div>
                <button type="button" className="ghost-button" onClick={() => props.onNavigate("channels")}>管理通道 <ArrowRight size={13} /></button>
              </div>
              <div className="home-radar-list">
                {props.loading && props.adapters.length === 0 ? <LoadingRows /> : adapterDataUnavailable && props.adapters.length === 0 ? (
                  <InlineState title="通道数据暂不可用" text={props.loadErrors.adapters} />
                ) : props.adapters.length === 0 ? (
                  <InlineState title="尚未配置通道" text="前往接入通道页面完成第一个通道配置。" />
                ) : props.adapters.map((adapter) => {
                  const status = props.adapterStatuses[adapter.name];
                  const statusError = typeof status?.error === "string" ? status.error : "";
                  const busy = props.adapterToggleBusy === adapter.name;
                  return (
                    <div key={adapter.name} className="home-radar-item">
                      <div className="home-radar-copy">
                        <span className={`status-dot ${adapter.started ? "status-dot--ok" : "status-dot--warn"}`} />
                        <div>
                          <strong>{channelDisplayName(adapter.name)}</strong>
                          <span>{statusError ? "状态读取失败" : adapter.name === "wechat869" ? "微信 · 客户端" : `${adapter.platform} · ${adapter.name}`}</span>
                        </div>
                      </div>
                      <div className="home-radar-actions">
                        <span className={`status-pill ${adapter.started ? "status-pill--ok" : "status-pill--neutral"}`}>{adapter.started ? "在线" : "未启动"}</span>
                        <button
                          type="button"
                          className={`ghost-button ghost-button--compact ${adapter.enabled ? "danger" : ""}`}
                          disabled={busy}
                          onClick={() => {
                            if (adapter.enabled && !window.confirm(`确认关闭 ${channelDisplayName(adapter.name)}？关闭后该通道将停止收发消息。`)) return;
                            void props.onToggleAdapter(adapter.name, adapter.enabled);
                          }}
                        >
                          {busy ? "处理中" : adapter.enabled ? "关闭" : "启用"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="card" aria-labelledby="home-extension-title">
              <div className="card__header">
                <div>
                  <div className="card__title" id="home-extension-title"><Zap size={18} /><span>插件与技能</span></div>
                  <div className="card__desc">启用 {enabledExtensions} 项，共安装 {extensionTotal} 项</div>
                </div>
                <button type="button" className="ghost-button" onClick={() => props.onNavigate("extensions")}>扩展管理 <ArrowRight size={13} /></button>
              </div>
              <div className="home-extension-grid">
                {props.loading && extensionTotal === 0 ? <LoadingRows /> : extensionDataUnavailable && extensionTotal === 0 ? (
                  <InlineState title="扩展数据暂不可用" text="请检查服务后重试。" />
                ) : extensionTotal === 0 ? (
                  <InlineState title="尚未安装扩展" text="插件和技能启用后会显示在这里。" />
                ) : [...props.plugins, ...props.skills].slice(0, 6).map((item) => (
                  <div className="home-extension-item" key={`${"tools" in item ? "skill" : "plugin"}:${item.name}`}>
                    <div><strong>{item.name}</strong><span>{item.description ? wechatChannelDisplayText(item.description) : `版本 ${item.version}`}</span></div>
                    <span className={`status-pill ${item.enabled ? "status-pill--ok" : "status-pill--neutral"}`}>{item.enabled ? "运行中" : "已停用"}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="home-column">
            <section className="card" aria-labelledby="home-actions-title">
              <div className="card__title" id="home-actions-title"><Sparkles size={18} /><span>常用入口</span></div>
              <div className="home-quick-actions">
                <QuickAction icon={<Bot size={19} />} label="Agent 对话" onClick={() => props.onNavigate("agentChat")} />
                <QuickAction icon={<MessagesSquare size={19} />} label="微信消息" onClick={() => props.onNavigate("wechat")} />
                <QuickAction icon={<BookOpenText size={19} />} label="群知识库" onClick={() => props.onNavigate("knowledge")} />
                <QuickAction icon={<Users size={19} />} label={`用户画像 ${props.profileCount || ""}`} onClick={() => props.onNavigate("profiles")} />
                <QuickAction icon={<Settings size={19} />} label="系统配置" onClick={() => props.onNavigate("settings")} />
              </div>
            </section>

            <section className="card home-events-card" aria-labelledby="home-events-title">
              <div className="card__header">
                <div className="card__title" id="home-events-title"><Activity size={17} /><span>实时事件</span></div>
                <span className={`status-pill status-pill--${props.websocketState === "connected" ? "ok" : props.websocketState === "connecting" ? "neutral" : "warn"}`}>{websocketLabels[props.websocketState]}</span>
              </div>
              <div className="home-event-list" aria-live="polite">
                {props.liveEvents.length === 0 ? (
                  <InlineState
                    title={props.websocketState === "connected" ? "正在监听事件" : websocketLabels[props.websocketState]}
                    text={props.websocketState === "connected" ? "新事件到达后会实时出现在这里。" : "连接恢复后事件会继续更新。"}
                  />
                ) : props.liveEvents.slice(0, 15).map((event, index) => (
                  <div className="home-event-item" key={event.id || index}>
                    <span>{event.type}</span><time>{formatTimeShort(event.created_at)}</time>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatButton(props: { icon: React.ReactNode; tone: string; value: React.ReactNode; label: string; detail: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="home-stat-card"
      onClick={props.onClick}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        props.onClick();
      }}
      aria-label={`${props.label}：${String(props.value)}`}
    >
      <span className={`home-stat-card__icon home-stat-card__icon--${props.tone}`}>{props.icon}</span>
      <span className="home-stat-card__info"><strong className="home-stat-card__num">{props.value}</strong><span className="home-stat-card__label">{props.label}</span><small>{props.detail}</small></span>
      <ArrowRight className="home-stat-card__arrow" size={16} aria-hidden="true" />
    </button>
  );
}

function QuickAction(props: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button type="button" className="home-quick-btn" onClick={props.onClick}>{props.icon}<span>{props.label}</span></button>;
}

function InlineState({ title, text }: { title: string; text: string }) {
  return <div className="home-inline-state"><strong>{title}</strong><span>{text}</span></div>;
}

function LoadingRows() {
  return <div className="home-loading" aria-label="加载中"><span /><span /><span /></div>;
}

function channelDisplayName(name: string): string {
  const names: Record<string, string> = { wechat_ilink: "微信 iLink", wechat869: WECHAT_CLIENT_LABEL, qq: "QQ 机器人", telegram: "Telegram", web: "Web" };
  return names[name] || name;
}

function formatTimeShort(value?: string | null): string {
  if (!value) return "刚刚";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
