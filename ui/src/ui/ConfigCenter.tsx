import {
  Boxes,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Eye,
  EyeOff,
  LoaderCircle,
  Network,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";
import { fieldCopy, optionCopy } from './settingsTasks';
import { WECHAT_CLIENT_LABEL, wechatChannelDisplayText } from "./wechatChannelLabel";
import type {
  ConfigApplyResult,
  ConfigChange,
  ConfigField,
  ConfigSection,
  ConfigSnapshot,
} from "../types";

type ConfigScope = "system" | "channels";
type DraftValue = string | boolean;

export type ConfigAppliedEvent = {
  apiToken?: string;
  result: ConfigApplyResult;
};

type ConfigCenterProps = {
  scope: ConfigScope;
  initialSection?: string;
  channel?: string;
  task?: { id: string; paths: string[]; snapshot: ConfigSnapshot; choices: string[] };
  onState?: (dirty: boolean, busy: boolean) => void;
  onFound?: (models: string[]) => void;
  onNext?: () => void;
  onApplied?: (event: ConfigAppliedEvent) => void | Promise<void>;
};

type EvaluatedChange = {
  field: ConfigField;
  change: ConfigChange;
};

type ModelPoolState = {
  discovered: string[];
  loading: boolean;
  loaded: boolean;
  error: string;
  connectionDirty: boolean;
  defaultModel: string;
  onDiscover: () => void;
};

const DRAFT_STORAGE_PREFIX = "xbot.config.draft.v1";
const SYSTEM_GROUPS = [
  { title: "智能体", keys: ["agent", "conversation"] },
  { title: "控制台", keys: ["xbot", "api"] },
  { title: "服务与数据", keys: ["network", "server", "storage", "queue", "runtime"] },
  { title: "扩展", keys: ["plugins", "skills"] },
];
const COMMON_FIELDS: Record<string, string[]> = {
  agent: ["enabled", "llm.enabled", "llm.provider", "llm.base_url", "llm.api_key", "llm.model", "llm.enabled_models"],
  "adapters.wechat869": ["enabled", "host", "port", "admin_key", "token_key", "ws_url"],
  "adapters.wechat_ilink": ["enabled", "base_url", "token"],
  "adapters.qq": ["enabled", "app_id", "client_secret"],
  "adapters.telegram": ["enabled", "bot_token", "api_base_url"],
};

function channelSnapshot(snapshot: ConfigSnapshot, channel?: string): ConfigSnapshot {
  if (!channel) return snapshot;
  const key = `adapters.${channel}`;
  return { ...snapshot, sections: snapshot.sections.filter(s => s.scope === "channels" && s.key === key),
    pending_restart: snapshot.pending_restart.filter(path => path.startsWith(`${key}.`)) };
}

export function ConfigCenter({ scope, initialSection = "", channel, task, onState, onFound, onNext, onApplied }: ConfigCenterProps) {
  const storageKey = `${DRAFT_STORAGE_PREFIX}.${scope}${channel ? `.${channel}` : task ? `.${task.id}` : ""}`;
  const project = useCallback((full: ConfigSnapshot) => !task ? channelSnapshot(full, channel) : ({ ...full,
    sections: full.sections.map(s=>({...s,fields:s.fields.filter(f=>task.paths.includes(f.path))})).filter(s=>s.fields.length),
    pending_restart:full.pending_restart.filter(p=>task.paths.includes(p)) }),[task,channel]);
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [draft, setDraft] = useState<Record<string, DraftValue>>({});
  const [resets, setResets] = useState<Record<string, boolean>>({});
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [selectedSection, setSelectedSection] = useState(initialSection);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const confirmation = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [draftSavedAt, setDraftSavedAt] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [modelsError, setModelsError] = useState("");

  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = project(task?.snapshot ?? await api.config());
      const nextDraft = buildDraft(next, scope);
      const restored = restoreDraft(next, scope, storageKey);
      setSnapshot(next);
      setDraft({ ...nextDraft, ...restored.values });
      setResets(restored.resets);
      setDraftSavedAt(restored.savedAt);
      setDiscoveredModels([]);
      setModelsLoaded(false);
      setModelsError("");
      const available = next.sections.filter((section) => section.scope === scope);
      const first = available.find((section) => section.key === "agent") ?? available[0];
      setSelectedSection((current) =>
        next.sections.some((section) => section.scope === scope && section.key === current)
          ? current
          : first?.key ?? "",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [scope, project, task, storageKey]);

  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  const scopedSections = useMemo(
    () => snapshot?.sections.filter((section) => section.scope === scope) ?? [],
    [scope, snapshot],
  );
  const allFields = useMemo(() => scopedSections.flatMap((section) => section.fields), [scopedSections]);
  const evaluation = useMemo(() => evaluateChanges(allFields, draft, resets), [allFields, draft, resets]);
  useEffect(()=>onState?.(evaluation.entries.length>0, saving || modelsLoading),[onState,evaluation.entries.length,saving,modelsLoading]);
  const enabledModelOptions = useMemo(
    () => parseListDraft(draft["agent.llm.enabled_models"]),
    [draft],
  );
  const modelConnectionDirty = evaluation.entries.some((entry) =>
    ["agent.llm.provider", "agent.llm.base_url", "agent.llm.api_key"].includes(entry.field.path),
  );

  useEffect(() => {
    if (!snapshot || loading) return;
    const timer = window.setTimeout(() => {
      const storedValues: Record<string, DraftValue> = {};
      for (const entry of evaluation.entries) {
        if (entry.field.secret || entry.change.reset) continue;
        const value = draft[entry.field.path];
        if (value !== undefined) storedValues[entry.field.path] = value;
      }
      const storedResets = evaluation.entries
        .filter((entry) => entry.change.reset)
        .map((entry) => entry.field.path);
      if (Object.keys(storedValues).length === 0 && storedResets.length === 0) {
        window.sessionStorage.removeItem(storageKey);
        setDraftSavedAt("");
        return;
      }
      const savedAt = new Date().toISOString();
      window.sessionStorage.setItem(
        storageKey,
        JSON.stringify({ revision: snapshot.revision, values: storedValues, resets: storedResets, savedAt }),
      );
      setDraftSavedAt(savedAt);
    }, 700);
    return () => window.clearTimeout(timer);
  }, [draft, evaluation.entries, loading, resets, storageKey, snapshot]);

  const normalizedQuery = query.trim().toLowerCase();
  const matchingSections = useMemo(
    () => scopedSections.filter((section) => sectionMatches(section, normalizedQuery)),
    [normalizedQuery, scopedSections],
  );

  useEffect(() => {
    if (matchingSections.length === 0) return;
    if (!matchingSections.some((section) => section.key === selectedSection)) {
      setSelectedSection(matchingSections[0].key);
    }
  }, [matchingSections, selectedSection]);

  const activeSection = matchingSections.find((section) => section.key === selectedSection) ?? matchingSections[0];
  const visibleFields = activeSection
    ? activeSection.fields.filter((field) => fieldMatches(field, normalizedQuery) || sectionOwnTextMatches(activeSection, normalizedQuery))
    : [];
  const commonKeys = activeSection && COMMON_FIELDS[activeSection.key];
  const taskFields = visibleFields.filter(f=>!(task?.id==='model' && f.path==='agent.llm.enabled_models'));
  const commonFields = task ? taskFields.filter(f=>task.id!=='connection' || f.path!=='agent.llm.provider') : commonKeys && !normalizedQuery
    ? commonKeys.flatMap((key) => visibleFields.filter((field) => field.path === `${activeSection.key}.${key}`))
    : visibleFields;
  const advancedFields = taskFields.filter((field) => !commonFields.includes(field));
  const navigation = scope === "channels" ? [{ title: "通道", sections: matchingSections }] : [
    ...SYSTEM_GROUPS.map(({ title, keys }) => ({
      title,
      sections: keys.flatMap((key) => matchingSections.filter((section) => section.key === key)),
    })),
    { title: "其他", sections: matchingSections.filter((section) => !SYSTEM_GROUPS.some(({ keys }) => keys.includes(section.key))) },
  ];
  const liveCount = evaluation.entries.filter((entry) => !entry.field.restart_required).length;
  const restartCount = evaluation.entries.filter((entry) => entry.field.restart_required).length;
  const secretCount = evaluation.entries.filter((entry) => entry.field.secret).length;
  const pendingRestartCount = snapshot?.pending_restart.length ?? 0;

  function updateField(path: string, value: DraftValue) {
    setDraft((current) => { const next={ ...current, [path]: value };
      if(task?.id==='model' && path==='agent.llm.model') {
        const pool=allFields.find(f=>f.path==='agent.llm.enabled_models');
        if(pool) next[pool.path]=Array.from(new Set([...parseListDraft(fieldDraftValue(pool)),String(value).trim()].filter(Boolean))).join('\n');
      } return next; });
    setResets((current) => ({ ...current, [path]: false }));
    setError("");
    setMessage("");
  }

  function toggleReset(field: ConfigField) {
    setResets((current) => ({ ...current, [field.path]: !current[field.path] }));
    setError("");
    setMessage("");
  }

  function clearDraft() {
    if (!snapshot) return;
    setDraft(buildDraft(snapshot, scope));
    setResets({});
    setVisibleSecrets({});
    setError("");
    setMessage("已放弃未应用的修改。");
    setDraftSavedAt("");
    window.sessionStorage.removeItem(storageKey);
  }

  async function discoverModels() {
    if (modelsLoading || modelConnectionDirty) return;
    setModelsLoading(true);
    setModelsError("");
    try {
      const result = await api.discoverLlmModels();
      onFound?.(result.models);
      setDiscoveredModels(result.models);
      setModelsLoaded(true);
    } catch (err) {
      setDiscoveredModels([]);
      setModelsLoaded(true);
      setModelsError(errorMessage(err));
    } finally {
      setModelsLoading(false);
    }
  }

  async function saveChanges() {
    if (!snapshot || evaluation.entries.length === 0 || saving) return;
    if (Object.keys(evaluation.errors).length > 0) {
      const firstPath = Object.keys(evaluation.errors)[0];
      document.getElementById(fieldDomId(firstPath))?.scrollIntoView({ behavior: "smooth", block: "center" });
      setError("还有字段格式不正确，请按字段下方提示修改后再保存。");
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    const shouldDiscoverModels = evaluation.entries.some((entry) =>
      ["agent.llm.provider", "agent.llm.base_url", "agent.llm.api_key"].includes(entry.field.path),
    );
    try {
      const result = await api.updateConfig({
        revision: snapshot.revision,
        changes: evaluation.entries.map((entry) => entry.change),
      });
      const apiTokenEntry = evaluation.entries.find(
        (entry) => entry.field.path === "api.token" && !entry.change.reset && typeof entry.change.value === "string",
      );
      const nextApiToken = apiTokenEntry && typeof apiTokenEntry.change.value === "string"
        ? apiTokenEntry.change.value
        : undefined;
      const next = project(result.snapshot);
      setSnapshot(next);
      setDraft(buildDraft(next, scope));
      setResets({});
      setVisibleSecrets({});
      setDraftSavedAt("");
      window.sessionStorage.removeItem(storageKey);
      const summary = [
        result.applied.length ? `${result.applied.length} 项已实时生效` : "",
        result.restart_required.length ? `${result.restart_required.length} 项等待重启` : "",
      ].filter(Boolean).join("，");
      setMessage(summary || "配置已保存，当前运行值没有变化。");
      if (shouldDiscoverModels) {
        setModelsLoading(true);
        setModelsError("");
        try {
          const discovery = await api.discoverLlmModels();
          onFound?.(discovery.models);
          setDiscoveredModels(discovery.models);
          setModelsLoaded(true);
        } catch (discoveryError) {
          setDiscoveredModels([]);
          setModelsLoaded(true);
          setModelsError(errorMessage(discoveryError));
        } finally {
          setModelsLoading(false);
        }
      }
      try {
        await onApplied?.({ apiToken: nextApiToken, result });
      } catch (refreshError) {
        setError(`配置已保存，但页面数据刷新失败：${errorMessage(refreshError)}`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading && !snapshot) {
    return <ConfigLoading scope={scope} />;
  }

  if (!snapshot) {
    return (
      <section className="config-center config-center--error">
        <CircleAlert size={24} />
        <h2>配置中心加载失败</h2>
        <p>{error || "后端没有返回配置快照。"}</p>
        <button className="primary-button" onClick={() => void loadSnapshot()}>
          <RefreshCw size={15} />
          重新加载
        </button>
      </section>
    );
  }

  return (
    <section className="config-center" aria-busy={saving}>
      {!task && <div className="config-center__toolbar">
        {!channel && <label className="config-search">
          <Search size={15} />
          <span className="sr-only">搜索配置</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            type="search"
            placeholder="搜索设置或环境变量"
          />
        </label>}
        <div className="config-center__header-actions">
          {pendingRestartCount ? <span className="config-chip config-chip--warn">{pendingRestartCount} 项待重启</span> : null}
          <button type="button" className="icon-button" title="重新读取配置" aria-label="重新读取配置"
            onClick={() => void loadSnapshot()}
            disabled={loading || saving || Boolean(evaluation.entries.length || Object.keys(evaluation.errors).length)}>
            <RefreshCw className={loading ? "spin" : ""} size={16} />
          </button>
        </div>
      </div>}

      {error ? <div className="config-notice config-notice--error" role="alert"><CircleAlert size={16} />{error}</div> : null}
      {message ? <div className="config-notice config-notice--success" aria-live="polite"><CheckCircle2 size={16} />{message}</div> : null}

      <div className="config-workflow">
        {!channel && !task && matchingSections.length > 0 && <div className="config-section-picker">
          <label htmlFor={`config-section-picker-${scope}`}>配置分区</label>
          <select id={`config-section-picker-${scope}`} value={activeSection?.key ?? ""}
            onChange={(event) => setSelectedSection(event.target.value)}>
            {navigation.filter(({ sections }) => sections.length).map(({ title, sections }) => <optgroup key={title} label={title}>
              {sections.map((section) => <option key={section.key} value={section.key}>{sectionDisplayTitle(section)}</option>)}
            </optgroup>)}
          </select>
        </div>}
        {!channel && !task && <nav className="config-section-rail" aria-label="配置分区">
          {navigation.filter(({ sections }) => sections.length).map(({ title, sections }) => <div key={title} className="config-nav-group">
            <div className="config-section-rail__label">{title}</div>
            {sections.map((section) => {
            const dirty = section.fields.filter((field) => evaluation.errors[field.path]
              || evaluation.entries.some((entry) => entry.field === field)).length;
            return (
              <button
                key={section.key}
                className={`config-section-button ${section.key === activeSection?.key ? "is-active" : ""}`}
                aria-current={section.key === activeSection?.key ? "true" : undefined}
                onClick={() => setSelectedSection(section.key)}
              >
                <strong>{sectionDisplayTitle(section)}</strong>
                {dirty ? <b>{dirty}</b> : <ChevronRight className="config-section-rail__arrow" size={17} />}
              </button>
            );
            })}
          </div>)}
        </nav>}

        <div className="config-form-column">
          {activeSection ? (
            <>
              {!task && <div className="config-section-intro">
                <div>
                  {!channel && <h2>{sectionDisplayTitle(activeSection)}</h2>}
                  <p>{activeSection.key === "agent" ? "模型连接、默认模型与可用模型。" : wechatChannelDisplayText(activeSection.description)}</p>
                </div>
              </div>}
              {task?.id==='connection' && !modelConnectionDirty && <div className="settings-discover">
                {modelsError && <p role="alert">连接信息未被撤销，但未能获取模型列表。{modelsError}</p>}
                {modelsLoaded && !modelsError && <p role="status">已获取 {discoveredModels.length} 个模型。此结果不代表已验证回复。</p>}
                <button className="ghost-button" disabled={modelsLoading || saving} onClick={()=>void discoverModels()}><RefreshCw size={14}/>{modelsLoading?'获取中…':modelsError?'重试获取模型':'获取模型列表'}</button>
                <button className="ghost-button" disabled={saving || modelsLoading || !!evaluation.entries.length} onClick={onNext}>选择默认模型 ›</button>
              </div>}
              {task?.id==='model' && <p className="config-field__description">新的模型 ID 会同时加入群聊可选列表，不改变已有群聊选择。</p>}
              <div className={`config-fields${activeSection.key === "agent" && !normalizedQuery ? " config-fields--model" : ""}`}>
                {[commonFields, advancedFields].map((fields, index) => {
                  if (!fields.length) return null;
                  const editors = fields.map((field) => (
                  <ConfigFieldEditor
                    key={field.path}
                    hideSource={Boolean(task)}
                    field={task && fieldCopy[field.path] ? {...field,label:fieldCopy[field.path][0],description:fieldCopy[field.path][1]} : field}
                    value={draft[field.path] ?? fieldDraftValue(field)}
                    reset={Boolean(resets[field.path])}
                    dirty={evaluation.entries.some((entry) => entry.field.path === field.path)}
                    error={evaluation.errors[field.path]}
                    visible={Boolean(visibleSecrets[field.path])}
                    optionsOverride={field.path === "agent.llm.model" ? task ? [...new Set([...task.choices,...parseListDraft(fieldDraftValue(allFields.find(f=>f.path==='agent.llm.enabled_models')!))])] : enabledModelOptions : undefined}
                    modelPool={field.path === "agent.llm.enabled_models" ? {
                      discovered: discoveredModels,
                      loading: modelsLoading,
                      loaded: modelsLoaded,
                      error: modelsError,
                      connectionDirty: modelConnectionDirty,
                    defaultModel: String(draft["agent.llm.model"] ?? task?.snapshot.sections.find(s=>s.key==='agent')?.fields.find(f=>f.path==='agent.llm.model')?.value ?? ""),
                      onDiscover: () => void discoverModels(),
                    } : undefined}
                    onChange={(value) => updateField(field.path, value)}
                    onToggleReset={() => toggleReset(field)}
                    onToggleVisible={() => setVisibleSecrets((current) => ({ ...current, [field.path]: !current[field.path] }))}
                  />
                  ));
                  if (!index) return editors;
                  const changed = fields.filter((field) => evaluation.entries.some((entry) => entry.field === field)
                    || evaluation.errors[field.path]).length;
                  return <details key={activeSection.key} className="config-advanced" open={changed ? true : undefined}>
                    <summary>{task?.id==='connection' ? '更多连接选项' : activeSection.key === "agent" ? "Hermes 与进阶参数" : "进阶参数"}</summary>
                    <div className="config-fields">{editors}</div>
                  </details>;
                })}
                {visibleFields.length === 0 ? (
                  <div className="config-empty">
                    <Search size={20} />
                    <strong>当前分区没有匹配字段</strong>
                    <span>清除搜索词后可查看完整配置。</span>
                  </div>
                ) : null}
                {task && <details className="config-advanced"><summary>技术详情与配置来源</summary>{taskFields.map(f=><div key={f.path} className="settings-source"><strong>{fieldCopy[f.path]?.[0] || f.label}</strong><small>{f.source==='web'?'网页设置':'环境变量或配置文件'} · {f.env_name || f.path}</small>{f.overridden && <button type="button" className="config-reset-link" onClick={()=>toggleReset(f)}>{resets[f.path]?'撤销恢复':'恢复配置来源'}</button>}</div>)}</details>}
              </div>
            </>
          ) : (
            <div className="config-empty">
              <Search size={20} />
              <strong>没有匹配的配置</strong>
              <span>尝试搜索其他名称或环境变量。</span>
            </div>
          )}
          {(evaluation.entries.length > 0 || Object.keys(evaluation.errors).length > 0) && (
              <div className="config-commit-bar">
                <div>
                  <strong>{Object.keys(evaluation.errors).length
                    ? `${Object.keys(evaluation.errors).length} 项格式待修正`
                    : `${evaluation.entries.length} 项修改未保存`}</strong>
                  <span>
                    {draftSavedAt
                      ? `非敏感草稿已暂存于本次浏览器会话 · ${formatClock(draftSavedAt)}`
                      : "敏感字段不会保存到浏览器草稿"}
                  </span>
                </div>
                <div className="config-commit-bar__actions">
                  <button className="ghost-button" onClick={clearDraft} disabled={saving}>
                    <RotateCcw size={14} />
                    放弃修改
                  </button>
                  <button
                    className="primary-button config-save-button"
                    onClick={() => confirmation.current?.showModal()}
                    disabled={!evaluation.entries.length || saving || Object.keys(evaluation.errors).length > 0}
                  >
                    {saving ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                    {saving ? "应用中…" : task?.id==='connection' ? '保存连接并获取模型' : "保存并应用"}
                  </button>
                </div>
              </div>
          )}
        </div>
      </div>
          <dialog
            ref={confirmation}
            className="config-confirm-dialog"
            aria-labelledby={`config-confirm-title-${scope}`}
            aria-describedby={`config-confirm-description-${scope}`}
            onClose={(event) => {
              const choice = event.currentTarget.returnValue;
              event.currentTarget.returnValue = "";
              if (choice === "apply") void saveChanges();
            }}
          >
            <div className="config-confirm-dialog__icon"><CircleAlert size={20} /></div>
            <div className="config-confirm-dialog__copy">
              <h1 id={`config-confirm-title-${scope}`}>确认保存并应用配置</h1>
              <p id={`config-confirm-description-${scope}`}>
                实时配置会短暂重建通道与 Agent 运行上下文。需要重启的字段只会安全写入配置文件。
              </p>
            </div>
            <div className="config-confirm-dialog__facts">
              <span><b>{evaluation.entries.length}</b> 项配置</span>
              <span><b>{liveCount}</b> 项实时生效</span>
              <span><b>{restartCount}</b> 项需要重启</span>
              <span><b>{secretCount}</b> 项敏感配置</span>
            </div>
            <ul className="config-confirm-changes">
              {evaluation.entries.map(({ field, change }) => <li key={field.path}>
                <span>{wechatChannelDisplayText(field.label)}</span>
                <small>{change.reset ? "恢复配置来源" : field.secret ? "更新密钥" : "已修改"}</small>
              </li>)}
            </ul>
            <form method="dialog" className="config-confirm-dialog__actions">
              <button type="submit" value="cancel" className="ghost-button" autoFocus>继续检查</button>
              <button
                type="submit"
                value="apply"
                className="primary-button"
              >
                <Save size={15} />
                确认保存并应用
              </button>
            </form>
          </dialog>
    </section>
  );
}

function ConfigFieldEditor({
  hideSource,
  field,
  value,
  reset,
  dirty,
  error,
  visible,
  optionsOverride,
  modelPool,
  onChange,
  onToggleReset,
  onToggleVisible,
}: {
  hideSource?: boolean;
  field: ConfigField;
  value: DraftValue;
  reset: boolean;
  dirty: boolean;
  error?: string;
  visible: boolean;
  optionsOverride?: string[];
  modelPool?: ModelPoolState;
  onChange: (value: DraftValue) => void;
  onToggleReset: () => void;
  onToggleVisible: () => void;
}) {
  const id = fieldDomId(field.path);
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const isWechatClient = field.path.startsWith("adapters.wechat869.");
  const describedBy = [field.description ? descriptionId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;

  return (
    <article id={id} className={`config-field${field.type === "boolean" ? " config-field--toggle" : ""} ${dirty ? "is-dirty" : ""} ${reset ? "is-reset" : ""} ${error ? "has-error" : ""}`}>
      <div className="config-field__head">
        <div className="config-field__title">
          <label htmlFor={`${id}-control`}>{wechatChannelDisplayText(field.label)}</label>
        </div>
        <div className="config-field__badges">
          {field.pending_restart || field.restart_required ? <span className="config-chip config-chip--warn">
            {field.pending_restart ? "等待重启" : "需重启"}
          </span> : null}
        </div>
      </div>

      {field.description ? <p id={descriptionId} className="config-field__description">{wechatChannelDisplayText(field.description)}</p> : null}

      {field.adapter_toggle ? (
        <div className="config-field__readonly">
          <CircleAlert size={16} />
          <span>启停状态由通道卡片上的开关管理。</span>
        </div>
      ) : reset ? (
        <div className="config-field__reset-state">
          <RotateCcw size={16} />
          <div>
            <strong>保存后恢复 ENV 或 TOML 来源</strong>
            <span>网页覆盖值会从运行时配置文件中删除。</span>
          </div>
          <button type="button" className="ghost-button" onClick={onToggleReset}>撤销恢复</button>
        </div>
      ) : (
        <FieldControl
          id={`${id}-control`}
          field={field}
          value={value}
          visible={visible}
          optionsOverride={optionsOverride}
          modelPool={modelPool}
          describedBy={describedBy}
          invalid={Boolean(error)}
          onChange={onChange}
          onToggleVisible={onToggleVisible}
        />
      )}

      {field.secret && !reset ? (
        <div className="config-field__secret-status">
          <ShieldCheck size={13} />
          <span>{field.configured ? `${field.masked_value || "已配置"}，留空保持现有值` : "尚未配置，保存后将只显示配置状态"}</span>
        </div>
      ) : null}
      {error ? <div id={errorId} className="config-field__error">{wechatChannelDisplayText(error)}</div> : null}
      {!hideSource && <details className="config-field__meta">
        <summary>配置来源</summary>
        <div>
          <span>{field.source === "web" ? "网页覆盖" : "ENV / TOML"}</span>
          {!isWechatClient && <> · <code>{field.path}</code>{field.env_name && <> · <code>{field.env_name}</code></>}</>}
        </div>
        {field.overridden && !field.adapter_toggle && !reset ? <button type="button" className="config-reset-link" onClick={onToggleReset}>
          <RotateCcw size={12} /> 恢复 ENV / TOML 来源
        </button> : null}
      </details>}
    </article>
  );
}

function FieldControl({
  id,
  field,
  value,
  visible,
  optionsOverride,
  modelPool,
  describedBy,
  invalid,
  onChange,
  onToggleVisible,
}: {
  id: string;
  field: ConfigField;
  value: DraftValue;
  visible: boolean;
  optionsOverride?: string[];
  modelPool?: ModelPoolState;
  describedBy?: string;
  invalid: boolean;
  onChange: (value: DraftValue) => void;
  onToggleVisible: () => void;
}) {
  if (field.path === "agent.llm.enabled_models" && modelPool) {
    return (
      <ModelPoolControl
        id={id}
        value={String(value)}
        describedBy={describedBy}
        invalid={invalid}
        state={modelPool}
        onChange={onChange}
      />
    );
  }

  if (field.type === "boolean") {
    const checked = Boolean(value);
    return (
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={describedBy}
        className={`config-switch ${checked ? "is-on" : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span><i /></span>
        <b>{checked ? "已启用" : "已停用"}</b>
      </button>
    );
  }

  const selectOptions = optionsOverride ?? field.options;
  if (field.path==='agent.llm.model' && optionsOverride) return <><input id={id} list={`${id}-choices`} value={String(value)} aria-describedby={describedBy} onChange={e=>onChange(e.target.value)} /><datalist id={`${id}-choices`}>{selectOptions.map(o=><option key={o} value={o}/>)}</datalist></>;
  if (selectOptions.length > 0) {
    if (!optionsOverride && selectOptions.every(o=>Object.hasOwn(optionCopy,o))) return (
      <div className="setting-choices" role="radiogroup" aria-label={field.label} aria-describedby={describedBy}>
        {selectOptions.map((o,i)=>{const [label,help]=optionCopy[o];const control=i===0?id:`${id}-${i}`;return <label key={o}>
          <input id={control} type="radio" name={id} value={o} checked={value===o} aria-labelledby={`${control}-name`} aria-describedby={`${control}-help`} onChange={()=>onChange(o)}/>
          <span><strong id={`${control}-name`}>{label}</strong><small id={`${control}-help`}>{help}</small></span>
        </label>;})}
      </div>
    );
    return (
      <select
        id={id}
        value={String(value)}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      >
        {selectOptions.map((option) => <option key={option} value={option}>{option==='openai_compatible'?'OpenAI 兼容接口':option==='anthropic'?'Anthropic 接口':option}</option>)}
      </select>
    );
  }

  if (field.type === "list" || field.type === "json") {
    return (
      <textarea
        id={id}
        value={String(value)}
        rows={field.type === "json" ? 8 : 4}
        spellCheck={false}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        placeholder={field.type === "json" ? (field.configured ? "粘贴完整 JSON 对象以覆盖现有配置" : "{}") : "每行一项，也支持逗号分隔"}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  const isNumber = field.type === "integer" || field.type === "number";
  return (
    <div className={field.secret ? "config-secret-input" : undefined}>
      <input
        id={id}
        type={field.secret ? (visible ? "text" : "password") : isNumber ? "number" : "text"}
        step={field.type === "integer" ? "1" : field.type === "number" ? "any" : undefined}
        value={String(value)}
        autoComplete={field.secret ? "new-password" : "off"}
        spellCheck={false}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        placeholder={field.secret && field.configured ? "留空保持现有值" : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {field.secret ? (
        <button type="button" title={visible ? "隐藏输入" : "显示输入"} aria-label={visible ? "隐藏输入" : "显示输入"} onClick={onToggleVisible}>
          {visible ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      ) : null}
    </div>
  );
}

function ModelPoolControl({
  id,
  value,
  describedBy,
  invalid,
  state,
  onChange,
}: {
  id: string;
  value: string;
  describedBy?: string;
  invalid: boolean;
  state: ModelPoolState;
  onChange: (value: DraftValue) => void;
}) {
  const [query, setQuery] = useState("");
  const enabled = parseListDraft(value);
  const [knownModels, setKnownModels] = useState<string[]>(enabled);
  useEffect(() => {
    setKnownModels((current) =>
      Array.from(new Set([...current, ...enabled, ...state.discovered])).sort((a, b) => a.localeCompare(b)),
    );
  }, [value, state.discovered]);
  const candidates = knownModels;
  const normalizedQuery = query.trim().toLowerCase();
  const visible = candidates.filter((model) => model.toLowerCase().includes(normalizedQuery));

  function toggle(model: string) {
    if (model === state.defaultModel) return;
    const next = enabled.includes(model)
      ? enabled.filter((item) => item !== model)
      : [...enabled, model];
    onChange(next.join("\n"));
  }

  return (
    <div id={id} className="model-pool" aria-describedby={describedBy} aria-invalid={invalid}>
      <div className="model-pool__toolbar">
        <div className="model-pool__identity">
          <span><Boxes size={17} /></span>
          <div><strong>{enabled.length} 个模型已启用</strong><small>群聊只能选择模型池中的模型</small></div>
        </div>
        <button
          type="button"
          className="ghost-button model-pool__discover"
          disabled={state.loading || state.connectionDirty}
          onClick={state.onDiscover}
        >
          <RefreshCw className={state.loading ? "spin" : ""} size={14} />
          {state.loading ? "获取中…" : "获取模型"}
        </button>
      </div>

      {state.connectionDirty ? (
        <div className="model-pool__notice model-pool__notice--warn"><CircleAlert size={14} />先保存 API 地址、协议或 Key，再自动获取最新模型。</div>
      ) : state.error ? (
        <div className="model-pool__notice model-pool__notice--error" role="alert"><CircleAlert size={14} />{state.error}</div>
      ) : state.loaded ? (
        <div className="model-pool__notice model-pool__notice--success"><CheckCircle2 size={14} />已发现 {state.discovered.length} 个模型，勾选后保存才会生效。</div>
      ) : (
        <div className="model-pool__notice"><Network size={14} />使用当前已生效的 API 地址和密钥读取模型列表。</div>
      )}

      {candidates.length ? (
        <>
          <label className="model-pool__search">
            <Search size={14} />
            <span className="sr-only">搜索模型</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索模型名称" />
          </label>
          <div className="model-pool__list">
            {visible.map((model) => {
              const checked = enabled.includes(model);
              const isDefault = model === state.defaultModel;
              return (
                <label key={model} className={`model-pool__item ${checked ? "is-checked" : ""}`}>
                  <input type="checkbox" checked={checked} disabled={isDefault} onChange={() => toggle(model)} />
                  <span><strong>{model}</strong><small>{isDefault ? "全局默认，不能移除" : checked ? "已启用" : "未启用"}</small></span>
                  {checked ? <Check size={15} /> : null}
                </label>
              );
            })}
            {!visible.length ? <div className="model-pool__empty">没有匹配的模型。</div> : null}
          </div>
        </>
      ) : (
        <div className="model-pool__empty">尚未发现模型。确认连接配置已保存后，点击“获取模型”。</div>
      )}
    </div>
  );
}

function ConfigLoading({ scope }: { scope: ConfigScope }) {
  return (
    <section className="config-center config-center--loading" aria-busy="true">
      <div className="config-loading__header">
        <span />
        <div><i /><i /></div>
      </div>
      <div className="config-loading__body">
        <div>{Array.from({ length: scope === "channels" ? 4 : 7 }, (_, index) => <i key={index} />)}</div>
        <div>{Array.from({ length: 4 }, (_, index) => <i key={index} />)}</div>
      </div>
    </section>
  );
}

function buildDraft(snapshot: ConfigSnapshot, scope: ConfigScope): Record<string, DraftValue> {
  const next: Record<string, DraftValue> = {};
  for (const section of snapshot.sections) {
    if (section.scope !== scope) continue;
    for (const field of section.fields) next[field.path] = fieldDraftValue(field);
  }
  return next;
}

function fieldDraftValue(field: ConfigField): DraftValue {
  if (field.secret) return "";
  if (field.type === "boolean") return Boolean(field.value);
  if (field.type === "list") return Array.isArray(field.value) ? field.value.map(String).join("\n") : "";
  if (field.type === "json") return JSON.stringify(field.value ?? {}, null, 2);
  return field.value === null || field.value === undefined ? "" : String(field.value);
}

function parseListDraft(value: DraftValue | undefined): string[] {
  if (typeof value !== "string") return [];
  return Array.from(new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)));
}

function evaluateChanges(fields: ConfigField[], draft: Record<string, DraftValue>, resets: Record<string, boolean>) {
  const entries: EvaluatedChange[] = [];
  const errors: Record<string, string> = {};
  for (const field of fields) {
    if (field.adapter_toggle) continue;
    if (resets[field.path] && field.overridden) {
      entries.push({ field, change: { path: field.path, reset: true } });
      continue;
    }
    const raw = draft[field.path] ?? fieldDraftValue(field);
    if (field.secret) {
      if (typeof raw === "string" && raw.length > 0) {
        try {
          const value = field.type === "json" || field.type === "list" ? parseValue(field, raw) : raw;
          entries.push({ field, change: { path: field.path, value } });
        } catch (err) {
          errors[field.path] = errorMessage(err);
        }
      }
      continue;
    }
    if (raw === fieldDraftValue(field)) continue;
    try {
      const value = parseValue(field, raw);
      entries.push({ field, change: { path: field.path, value } });
    } catch (err) {
      errors[field.path] = errorMessage(err);
      entries.push({ field, change: { path: field.path, value: raw } });
    }
  }
  return { entries, errors };
}

function parseValue(field: ConfigField, raw: DraftValue): unknown {
  if (field.type === "boolean") return Boolean(raw);
  const text = String(raw);
  if (field.type === "integer") {
    if (!/^-?\d+$/.test(text.trim())) throw new Error("请输入完整整数，例如 30。" );
    const value = Number(text);
    if (!Number.isSafeInteger(value)) throw new Error("整数超出安全范围，请输入更小的数值。" );
    return value;
  }
  if (field.type === "number") {
    const value = Number(text);
    if (!text.trim() || !Number.isFinite(value)) throw new Error("请输入有效数字，例如 1.5。" );
    return value;
  }
  if (field.type === "list") {
    return text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
  }
  if (field.type === "json") {
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch {
      throw new Error("JSON 格式不正确，请检查引号、逗号和括号。" );
    }
    if (!value || Array.isArray(value) || typeof value !== "object") {
      throw new Error("这里需要一个 JSON 对象，例如 {}。" );
    }
    return value;
  }
  return text;
}

function sectionMatches(section: ConfigSection, query: string): boolean {
  if (!query) return true;
  return sectionOwnTextMatches(section, query) || section.fields.some((field) => fieldMatches(field, query));
}

function sectionDisplayTitle(section: ConfigSection): string {
  if (section.key === "adapters.wechat869") return WECHAT_CLIENT_LABEL;
  if (section.key === "agent") return "模型配置";
  return section.title;
}

function sectionOwnTextMatches(section: ConfigSection, query: string): boolean {
  if (!query) return true;
  return [sectionDisplayTitle(section), section.title, section.key].some((value) => value.toLowerCase().includes(query));
}

function fieldMatches(field: ConfigField, query: string): boolean {
  if (!query) return true;
  return [field.label, field.description, field.path, field.env_name]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(query));
}

function restoreDraft(snapshot: ConfigSnapshot, scope: ConfigScope, storageKey: string): { values: Record<string, DraftValue>; resets: Record<string, boolean>; savedAt: string } {
  const empty = { values: {}, resets: {}, savedAt: "" } as { values: Record<string, DraftValue>; resets: Record<string, boolean>; savedAt: string };
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (!raw) return empty;
    const stored = JSON.parse(raw) as { revision?: string; values?: Record<string, DraftValue>; resets?: string[]; savedAt?: string };
    if (stored.revision !== snapshot.revision) {
      window.sessionStorage.removeItem(storageKey);
      return empty;
    }
    const allowedFields = snapshot.sections.filter((section) => section.scope === scope).flatMap((section) => section.fields);
    const allowed = new Map(allowedFields.map((field) => [field.path, field]));
    const values: Record<string, DraftValue> = {};
    for (const [path, value] of Object.entries(stored.values ?? {})) {
      const field = allowed.get(path);
      if (field && !field.secret && (typeof value === "string" || typeof value === "boolean")) values[path] = value;
    }
    const resets: Record<string, boolean> = {};
    for (const path of stored.resets ?? []) {
      const field = allowed.get(path);
      if (field?.overridden) resets[path] = true;
    }
    return { values, resets, savedAt: stored.savedAt ?? "" };
  } catch {
    window.sessionStorage.removeItem(storageKey);
    return empty;
  }
}

function fieldDomId(path: string): string {
  return `config-field-${path.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

function errorMessage(error: unknown): string {
  return wechatChannelDisplayText(error instanceof Error ? error.message : String(error));
}
