import { Activity, CalendarClock, CircleStop, Clock3, Pause, Play, Plus, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AgentEvent, BackgroundTask, ScheduledJob, UiEvent } from "../types";
import { wechatChannelDisplayText } from "./wechatChannelLabel";

type Tab = "background" | "schedules" | "events";

export function OperationsCenter({ events, liveEvents }: { events: AgentEvent[]; liveEvents: UiEvent[] }) {
  const [tab, setTab] = useState<Tab>("background");
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [schedule, setSchedule] = useState("");
  const [input, setInput] = useState("");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [maxRuns, setMaxRuns] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const [taskResult, jobResult] = await Promise.allSettled([api.backgroundTasks(50), api.scheduledJobs(100)]);
    const failures: string[] = [];
    if (taskResult.status === "fulfilled") setTasks(taskResult.value);
    else failures.push(`后台任务：${errorMessage(taskResult.reason)}`);
    if (jobResult.status === "fulfilled") setJobs(jobResult.value);
    else failures.push(`定时任务：${errorMessage(jobResult.reason)}`);
    setError(failures.join("；"));
    setLoading(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function runTaskAction(action: "replay" | "cancel", taskId: string) {
    if (action === "cancel" && !window.confirm("确认取消该后台任务？")) return;
    setBusyId(taskId);
    setError("");
    try {
      if (action === "replay") await api.replayBackgroundTask(taskId);
      else await api.cancelBackgroundTask(taskId);
      setTasks(await api.backgroundTasks(50));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyId("");
    }
  }

  async function runJobAction(action: "pause" | "resume" | "run" | "delete", jobId: string) {
    if (action === "delete" && !window.confirm("确认删除该定时任务？删除后无法恢复。")) return;
    setBusyId(jobId);
    setError("");
    try {
      if (action === "pause") await api.pauseScheduledJob(jobId);
      if (action === "resume") await api.resumeScheduledJob(jobId);
      if (action === "run") await api.runScheduledJob(jobId);
      if (action === "delete") await api.deleteScheduledJob(jobId);
      setJobs(await api.scheduledJobs(100));
      if (action === "run") setTasks(await api.backgroundTasks(50));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyId("");
    }
  }

  async function createJob() {
    if (!schedule.trim() || !input.trim()) {
      setError("请填写执行计划和任务指令。");
      return;
    }
    const parsedMaxRuns = maxRuns.trim() ? Number(maxRuns) : null;
    if (parsedMaxRuns !== null && (!Number.isInteger(parsedMaxRuns) || parsedMaxRuns < 1)) {
      setError("最大执行次数必须是大于 0 的整数。");
      return;
    }
    setBusyId("create");
    setError("");
    try {
      await api.createScheduledJob({
        name: name.trim() || undefined,
        schedule: schedule.trim(),
        input: input.trim(),
        timezone: timezone.trim() || "Asia/Shanghai",
        max_runs: parsedMaxRuns,
        source: "control-ui:schedule",
        reply_policy: "none",
      });
      setName("");
      setSchedule("");
      setInput("");
      setMaxRuns("");
      setJobs(await api.scheduledJobs(100));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="operations-center">
      <div className="operations-head">
        <div><h2>任务与自动化</h2><p>后台任务、定时计划与实时活动统一管理。</p></div>
        <button type="button" className="ghost-button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} />{loading ? "刷新中" : "刷新"}</button>
      </div>

      <div className="operations-tabs" role="tablist" aria-label="任务管理分类">
        <TabButton active={tab === "background"} icon={<Clock3 size={16} />} label={`后台任务 ${tasks.length}`} onClick={() => setTab("background")} />
        <TabButton active={tab === "schedules"} icon={<CalendarClock size={16} />} label={`定时任务 ${jobs.length}`} onClick={() => setTab("schedules")} />
        <TabButton active={tab === "events"} icon={<Activity size={16} />} label={`活动流 ${events.length + liveEvents.length}`} onClick={() => setTab("events")} />
      </div>

      {error && <div className="error-banner" role="alert">{error}</div>}

      {tab === "background" && (
        <div className="operations-panel" role="tabpanel">
          {loading && tasks.length === 0 ? <Empty title="正在读取后台任务" text="请稍候。" /> : tasks.length === 0 ? (
            <Empty title="暂无后台任务" text="Agent 创建的异步任务会显示在这里。" />
          ) : (
            <div className="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>来源</th><th>进度 / 结果</th><th>创建时间</th><th>操作</th></tr></thead><tbody>
              {tasks.map((task) => <tr key={task.id}>
                <td><strong>{task.description || task.kind}</strong><small className="table-subtext">{task.id}</small></td>
                <td><Status value={task.status} /></td><td>{wechatChannelDisplayText(task.source)}</td><td className="operations-result">{task.error ? wechatChannelDisplayText(task.error) : task.progress || stringifyCompact(task.result) || "—"}</td><td>{formatDate(task.created_at)}</td>
                <td><div className="table-actions">
                  <button type="button" className="icon-button" title="重试" disabled={busyId === task.id} onClick={() => void runTaskAction("replay", task.id)}><RotateCcw size={14} /></button>
                  <button type="button" className="icon-button danger" title="取消" disabled={busyId === task.id || terminalStatus(task.status)} onClick={() => void runTaskAction("cancel", task.id)}><CircleStop size={14} /></button>
                </div></td>
              </tr>)}
            </tbody></table></div>
          )}
        </div>
      )}

      {tab === "schedules" && (
        <div className="operations-schedule-grid" role="tabpanel">
          <form className="operations-create card" onSubmit={(event) => { event.preventDefault(); void createJob(); }}>
            <div className="card__title"><Plus size={17} /><span>新建定时任务</span></div>
            <label><span>名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：每日群聊总结" /></label>
            <label><span>执行计划</span><input value={schedule} onChange={(event) => setSchedule(event.target.value)} placeholder="daily 09:00 / every 2h / Cron" required /></label>
            <label><span>任务指令</span><textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入 Agent 需要执行的任务" rows={5} required /></label>
            <div className="operations-form-row"><label><span>时区</span><input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label><label><span>最多执行</span><input type="number" min="1" value={maxRuns} onChange={(event) => setMaxRuns(event.target.value)} placeholder="不限" /></label></div>
            <button type="submit" className="primary-button" disabled={busyId === "create"}>{busyId === "create" ? "创建中" : "创建任务"}</button>
          </form>
          <div className="operations-panel">
            {loading && jobs.length === 0 ? <Empty title="正在读取定时任务" text="请稍候。" /> : jobs.length === 0 ? (
              <Empty title="暂无定时任务" text="在左侧创建第一个自动化计划。" />
            ) : <div className="schedule-card-list">{jobs.map((job) => <article className="schedule-card" key={job.id}>
              <div className="schedule-card__head"><div><strong>{job.name || "未命名任务"}</strong><span>{job.schedule_display}</span></div><Status value={job.enabled ? (job.last_status || "enabled") : "paused"} /></div>
              <p>{job.input}</p><dl><div><dt>下次运行</dt><dd>{formatDate(job.next_run_at)}</dd></div><div><dt>已运行</dt><dd>{job.run_count}{job.max_runs ? ` / ${job.max_runs}` : " 次"}</dd></div><div><dt>时区</dt><dd>{job.timezone}</dd></div></dl>
              {job.last_error && <div className="schedule-card__error">{wechatChannelDisplayText(job.last_error)}</div>}
              <div className="table-actions">
                <button type="button" className="ghost-button ghost-button--compact" disabled={busyId === job.id} onClick={() => void runJobAction("run", job.id)}><Play size={13} />立即运行</button>
                <button type="button" className="ghost-button ghost-button--compact" disabled={busyId === job.id} onClick={() => void runJobAction(job.enabled ? "pause" : "resume", job.id)}>{job.enabled ? <Pause size={13} /> : <Play size={13} />}{job.enabled ? "暂停" : "恢复"}</button>
                <button type="button" className="icon-button danger" title="删除" disabled={busyId === job.id} onClick={() => void runJobAction("delete", job.id)}><Trash2 size={14} /></button>
              </div>
            </article>)}</div>}
          </div>
        </div>
      )}

      {tab === "events" && <EventStream events={events} liveEvents={liveEvents} />}
    </section>
  );
}

function TabButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button type="button" role="tab" aria-selected={active} className={active ? "is-active" : ""} onClick={onClick}>{icon}{label}</button>;
}

function EventStream({ events, liveEvents }: { events: AgentEvent[]; liveEvents: UiEvent[] }) {
  const items = [
    ...liveEvents.map((event) => ({ id: event.id, type: event.type, topic: event.topic, content: event.data, createdAt: event.created_at })),
    ...events.map((event, index) => ({ id: `${event.task_id}:${event.type}:${index}`, type: event.type, topic: event.task_id, content: event.content, createdAt: event.created_at })),
  ].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()).slice(0, 150);
  return <div className="operations-panel event-stream" role="tabpanel">{items.length === 0 ? <Empty title="暂无活动事件" text="WebSocket 与 Agent 事件到达后会显示在这里。" /> : items.map((item) => <details key={item.id} className="event-card"><summary><span><strong>{item.type}</strong><small>{wechatChannelDisplayText(item.topic)}</small></span><time>{formatDate(item.createdAt)}</time></summary><pre>{stringifyCompact(item.content) || "无附加内容"}</pre></details>)}</div>;
}

function Status({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const tone = ["completed", "success", "running", "enabled"].some((item) => normalized.includes(item)) ? "ok" : ["failed", "error", "cancel"].some((item) => normalized.includes(item)) ? "warn" : "neutral";
  return <span className={`status-pill status-pill--${tone}`}>{value}</span>;
}

function Empty({ title, text }: { title: string; text: string }) {
  return <div className="operations-empty"><strong>{title}</strong><span>{text}</span></div>;
}

function terminalStatus(value: string): boolean { return ["completed", "failed", "cancelled"].includes(value.toLowerCase()); }
function errorMessage(reason: unknown): string { return wechatChannelDisplayText(reason instanceof Error ? reason.message : String(reason)); }
function stringifyCompact(value: unknown): string {
  if (value == null || value === "") return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, (key, item) => (
    typeof item === "string" && ["adapter", "conversation_id", "source"].includes(key) ? wechatChannelDisplayText(item) : item
  ));
}
function formatDate(value?: string | null): string { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false }); }
