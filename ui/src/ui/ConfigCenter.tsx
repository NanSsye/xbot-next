import {
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Eye,
  EyeOff,
  FileKey2,
  LoaderCircle,
  Network,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ServerCog,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api";
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
  onApplied?: (event: ConfigAppliedEvent) => void | Promise<void>;
};

type EvaluatedChange = {
  field: ConfigField;
  change: ConfigChange;
  preview: string;
};

const DRAFT_STORAGE_PREFIX = "xbot.config.draft.v1";

export function ConfigCenter({ scope, onApplied }: ConfigCenterProps) {
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [draft, setDraft] = useState<Record<string, DraftValue>>({});
  const [resets, setResets] = useState<Record<string, boolean>>({});
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [selectedSection, setSelectedSection] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [draftSavedAt, setDraftSavedAt] = useState("");

  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await api.config();
      const nextDraft = buildDraft(next, scope);
      const restored = restoreDraft(next, scope);
      setSnapshot(next);
      setDraft({ ...nextDraft, ...restored.values });
      setResets(restored.resets);
      setDraftSavedAt(restored.savedAt);
      const first = next.sections.find((section) => section.scope === scope);
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
  }, [scope]);

  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  const scopedSections = useMemo(
    () => snapshot?.sections.filter((section) => section.scope === scope) ?? [],
    [scope, snapshot],
  );
  const allFields = useMemo(() => scopedSections.flatMap((section) => section.fields), [scopedSections]);
  const evaluation = useMemo(() => evaluateChanges(allFields, draft, resets), [allFields, draft, resets]);

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
      const storageKey = draftStorageKey(scope);
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
  }, [draft, evaluation.entries, loading, resets, scope, snapshot]);

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
  const liveCount = evaluation.entries.filter((entry) => !entry.field.restart_required).length;
  const restartCount = evaluation.entries.filter((entry) => entry.field.restart_required).length;
  const secretCount = evaluation.entries.filter((entry) => entry.field.secret).length;
  const pendingRestartCount = snapshot?.pending_restart.length ?? 0;

  useEffect(() => {
    if (!confirming) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setConfirming(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [confirming]);

  function updateField(path: string, value: DraftValue) {
    setDraft((current) => ({ ...current, [path]: value }));
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
    setConfirming(false);
    setDraftSavedAt("");
    window.sessionStorage.removeItem(draftStorageKey(scope));
  }

  async function saveChanges() {
    if (!snapshot || evaluation.entries.length === 0 || saving) return;
    if (Object.keys(evaluation.errors).length > 0) {
      const firstPath = Object.keys(evaluation.errors)[0];
      document.getElementById(fieldDomId(firstPath))?.scrollIntoView({ behavior: "smooth", block: "center" });
      setError("还有字段格式不正确，请按字段下方提示修改后再保存。");
      return;
    }
    setConfirming(false);
    setSaving(true);
    setError("");
    setMessage("");
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
      setSnapshot(result.snapshot);
      setDraft(buildDraft(result.snapshot, scope));
      setResets({});
      setVisibleSecrets({});
      setDraftSavedAt("");
      window.sessionStorage.removeItem(draftStorageKey(scope));
      const summary = [
        result.applied.length ? `${result.applied.length} 项已实时生效` : "",
        result.restart_required.length ? `${result.restart_required.length} 项等待重启` : "",
      ].filter(Boolean).join("，");
      setMessage(summary || "配置已保存，当前运行值没有变化。");
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

  const HeaderIcon = scope === "channels" ? Network : ServerCog;
  return (
    <section className="config-center" aria-busy={saving}>
      <header className="config-center__header">
        <div className="config-center__identity">
          <span className="config-center__icon"><HeaderIcon size={20} /></span>
          <div>
            <h2>{scope === "channels" ? "通道参数" : "系统配置中心"}</h2>
            <p>
              {scope === "channels"
                ? "配置 Web、微信与 QQ 官方机器人参数。保存后会重建通道运行上下文。"
                : "管理 xbot 支持的 ENV 与 TOML 参数。网页覆盖优先，密钥只写入服务端。"}
            </p>
          </div>
        </div>
        <div className="config-center__header-actions">
          {pendingRestartCount ? <span className="config-chip config-chip--warn">{pendingRestartCount} 项待重启</span> : null}
          <span className="config-chip config-chip--ok"><Zap size={12} /> 支持热生效</span>
          <button className="icon-button" title="重新读取配置" onClick={() => void loadSnapshot()} disabled={loading || saving}>
            <RefreshCw className={loading ? "spin" : ""} size={16} />
          </button>
        </div>
      </header>

      <div className="config-center__toolbar">
        <label className="config-search">
          <Search size={15} />
          <span className="sr-only">搜索配置</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索名称、配置路径或 ENV 变量"
          />
        </label>
        <div className="config-center__summary">
          <span>{scopedSections.length} 个分区</span>
          <span>{allFields.length} 个字段</span>
          <span className={evaluation.entries.length ? "is-dirty" : ""}>{evaluation.entries.length} 项修改</span>
        </div>
      </div>

      {error ? <div className="config-notice config-notice--error" role="alert"><CircleAlert size={16} />{error}</div> : null}
      {message ? <div className="config-notice config-notice--success" aria-live="polite"><CheckCircle2 size={16} />{message}</div> : null}

      <div className="config-workflow">
        <nav className="config-section-rail" aria-label="配置分区">
          <div className="config-section-rail__label">配置分区</div>
          {matchingSections.map((section) => {
            const dirty = evaluation.entries.filter((entry) => entry.field.path.startsWith(`${section.key}.`) || section.fields.some((field) => field.path === entry.field.path)).length;
            return (
              <button
                key={section.key}
                className={section.key === activeSection?.key ? "is-active" : ""}
                onClick={() => setSelectedSection(section.key)}
              >
                <span>
                  <strong>{section.title}</strong>
                  <small>{section.fields.length} 个字段</small>
                </span>
                {dirty ? <b>{dirty}</b> : <ChevronRight className="config-section-rail__arrow" size={17} />}
              </button>
            );
          })}
          {matchingSections.length === 0 ? <p>没有匹配的配置分区。</p> : null}
        </nav>

        <main className="config-form-column">
          {activeSection ? (
            <>
              <div className="config-section-intro">
                <div>
                  <h3>{activeSection.title}</h3>
                  <p>{activeSection.description}</p>
                </div>
                <span className="config-chip">{activeSection.key}</span>
              </div>
              <div className="config-fields">
                {visibleFields.map((field) => (
                  <ConfigFieldEditor
                    key={field.path}
                    field={field}
                    value={draft[field.path] ?? fieldDraftValue(field)}
                    reset={Boolean(resets[field.path])}
                    dirty={evaluation.entries.some((entry) => entry.field.path === field.path)}
                    error={evaluation.errors[field.path]}
                    visible={Boolean(visibleSecrets[field.path])}
                    onChange={(value) => updateField(field.path, value)}
                    onToggleReset={() => toggleReset(field)}
                    onToggleVisible={() => setVisibleSecrets((current) => ({ ...current, [field.path]: !current[field.path] }))}
                  />
                ))}
                {visibleFields.length === 0 ? (
                  <div className="config-empty">
                    <Search size={20} />
                    <strong>当前分区没有匹配字段</strong>
                    <span>清除搜索词后可查看完整配置。</span>
                  </div>
                ) : null}
              </div>
              <div className="config-commit-bar">
                <div>
                  <strong>{evaluation.entries.length ? `${evaluation.entries.length} 项修改等待应用` : "当前配置已同步"}</strong>
                  <span>
                    {draftSavedAt
                      ? `非敏感草稿已暂存于本次浏览器会话 · ${formatClock(draftSavedAt)}`
                      : "敏感字段不会保存到浏览器草稿"}
                  </span>
                </div>
                <div className="config-commit-bar__actions">
                  <button className="ghost-button" onClick={clearDraft} disabled={!evaluation.entries.length || saving}>
                    <RotateCcw size={14} />
                    放弃修改
                  </button>
                  <button
                    className="primary-button config-save-button"
                    onClick={() => setConfirming(true)}
                    disabled={!evaluation.entries.length || saving || Object.keys(evaluation.errors).length > 0}
                  >
                    {saving ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                    {saving ? "应用中…" : "保存并应用"}
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="config-empty">
              <Search size={20} />
              <strong>没有匹配的配置</strong>
              <span>尝试搜索其他名称或 ENV 变量。</span>
            </div>
          )}
        </main>

        <aside className="config-inspector">
          <div className="config-inspector__head">
            <ShieldCheck size={17} />
            <div>
              <strong>应用检查</strong>
              <span>保存前实时核对影响范围</span>
            </div>
          </div>
          <div className="config-check-list">
            <CheckRow ok={Object.keys(evaluation.errors).length === 0} label="字段格式" value={Object.keys(evaluation.errors).length ? `${Object.keys(evaluation.errors).length} 项需修正` : "检查通过"} />
            <CheckRow ok label="即时生效" value={`${liveCount} 项`} />
            <CheckRow ok={restartCount === 0} tone={restartCount ? "warn" : "ok"} label="需要重启" value={`${restartCount} 项`} />
            <CheckRow ok label="敏感配置" value={`${secretCount} 项`} />
          </div>
          <div className="config-inspector__changes">
            <div className="config-inspector__section-title">本次变更</div>
            {evaluation.entries.length ? evaluation.entries.slice(0, 8).map((entry) => (
              <button
                key={entry.field.path}
                onClick={() => {
                  const section = scopedSections.find((item) => item.fields.some((field) => field.path === entry.field.path));
                  if (section) setSelectedSection(section.key);
                  window.setTimeout(() => document.getElementById(fieldDomId(entry.field.path))?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
                }}
              >
                <span>{entry.field.label}</span>
                <small>{entry.preview}</small>
              </button>
            )) : <p>修改字段后，这里会列出实际生效内容。</p>}
            {evaluation.entries.length > 8 ? <div className="config-inspector__more">另有 {evaluation.entries.length - 8} 项修改</div> : null}
          </div>
          <div className="config-security-note">
            <FileKey2 size={17} />
            <div>
              <strong>密钥保护</strong>
              <p>API 永不回传明文密钥。留空表示保持原值，“恢复来源”会删除网页覆盖。</p>
            </div>
          </div>
          <div className="config-source-legend">
            <span><i className="is-web" /> 网页覆盖</span>
            <span><i /> ENV 或 TOML</span>
            <span><Zap size={12} /> 实时生效</span>
            <span><RefreshCw size={12} /> 需重启</span>
          </div>
        </aside>
      </div>
      {confirming ? (
        <div className="config-confirm-backdrop" onMouseDown={() => setConfirming(false)}>
          <section
            className="config-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={`config-confirm-title-${scope}`}
            aria-describedby={`config-confirm-description-${scope}`}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="config-confirm-dialog__icon"><CircleAlert size={20} /></div>
            <div className="config-confirm-dialog__copy">
              <h3 id={`config-confirm-title-${scope}`}>确认保存并应用配置</h3>
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
            <div className="config-confirm-dialog__actions">
              <button type="button" className="ghost-button" onClick={() => setConfirming(false)}>继续检查</button>
              <button
                type="button"
                className="primary-button"
                autoFocus
                onClick={() => void saveChanges()}
              >
                <Save size={15} />
                确认保存并应用
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function ConfigFieldEditor({
  field,
  value,
  reset,
  dirty,
  error,
  visible,
  onChange,
  onToggleReset,
  onToggleVisible,
}: {
  field: ConfigField;
  value: DraftValue;
  reset: boolean;
  dirty: boolean;
  error?: string;
  visible: boolean;
  onChange: (value: DraftValue) => void;
  onToggleReset: () => void;
  onToggleVisible: () => void;
}) {
  const id = fieldDomId(field.path);
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const describedBy = [field.description ? descriptionId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;

  return (
    <article id={id} className={`config-field ${dirty ? "is-dirty" : ""} ${reset ? "is-reset" : ""} ${error ? "has-error" : ""}`}>
      <div className="config-field__head">
        <div className="config-field__title">
          <label htmlFor={`${id}-control`}>{field.label}</label>
          <code>{field.path}</code>
        </div>
        <div className="config-field__badges">
          {field.secret ? <span className="config-chip config-chip--secret"><FileKey2 size={11} /> 敏感</span> : null}
          <span className={`config-chip ${field.source === "web" ? "config-chip--web" : ""}`}>
            {field.source === "web" ? "网页覆盖" : "ENV/TOML"}
          </span>
          <span className={`config-chip ${field.restart_required ? "config-chip--warn" : "config-chip--ok"}`}>
            {field.restart_required ? "需重启" : "即时生效"}
          </span>
        </div>
      </div>

      <div className="config-field__meta">
        {field.env_name ? <span>{field.env_name}</span> : <span>仅 TOML 配置</span>}
        {field.pending_restart ? <b>当前值等待重启</b> : null}
      </div>
      {field.description ? <p id={descriptionId} className="config-field__description">{field.description}</p> : null}

      {field.adapter_toggle ? (
        <div className="config-field__readonly">
          <CircleAlert size={16} />
          <span>通道启停请在“运行状态”页操作。该开关会立即执行并保存。</span>
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
      {error ? <div id={errorId} className="config-field__error">{error}</div> : null}
      {field.overridden && !field.adapter_toggle && !reset ? (
        <button type="button" className="config-reset-link" onClick={onToggleReset}>
          <RotateCcw size={12} />
          恢复 ENV/TOML 来源
        </button>
      ) : null}
    </article>
  );
}

function FieldControl({
  id,
  field,
  value,
  visible,
  describedBy,
  invalid,
  onChange,
  onToggleVisible,
}: {
  id: string;
  field: ConfigField;
  value: DraftValue;
  visible: boolean;
  describedBy?: string;
  invalid: boolean;
  onChange: (value: DraftValue) => void;
  onToggleVisible: () => void;
}) {
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

  if (field.options.length > 0) {
    return (
      <select
        id={id}
        value={String(value)}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      >
        {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
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

function CheckRow({ ok, tone = ok ? "ok" : "error", label, value }: { ok: boolean; tone?: "ok" | "warn" | "error"; label: string; value: string }) {
  return (
    <div className={`config-check-row config-check-row--${tone}`}>
      <span>{ok ? <Check size={13} /> : <CircleAlert size={13} />}</span>
      <b>{label}</b>
      <small>{value}</small>
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
        <main>{Array.from({ length: 4 }, (_, index) => <i key={index} />)}</main>
        <aside>{Array.from({ length: 3 }, (_, index) => <i key={index} />)}</aside>
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

function evaluateChanges(fields: ConfigField[], draft: Record<string, DraftValue>, resets: Record<string, boolean>) {
  const entries: EvaluatedChange[] = [];
  const errors: Record<string, string> = {};
  for (const field of fields) {
    if (field.adapter_toggle) continue;
    if (resets[field.path] && field.overridden) {
      entries.push({ field, change: { path: field.path, reset: true }, preview: "恢复 ENV/TOML" });
      continue;
    }
    const raw = draft[field.path] ?? fieldDraftValue(field);
    if (field.secret) {
      if (typeof raw === "string" && raw.length > 0) {
        try {
          const value = field.type === "json" || field.type === "list" ? parseValue(field, raw) : raw;
          entries.push({ field, change: { path: field.path, value }, preview: "更新密钥" });
        } catch (err) {
          errors[field.path] = errorMessage(err);
        }
      }
      continue;
    }
    if (raw === fieldDraftValue(field)) continue;
    try {
      const value = parseValue(field, raw);
      entries.push({ field, change: { path: field.path, value }, preview: previewValue(value) });
    } catch (err) {
      errors[field.path] = errorMessage(err);
      entries.push({ field, change: { path: field.path, value: raw }, preview: "格式待修正" });
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

function previewValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "启用" : "停用";
  if (Array.isArray(value)) return `${value.length} 项`;
  if (value && typeof value === "object") return "更新 JSON 对象";
  const text = String(value);
  return text.length > 32 ? `${text.slice(0, 29)}…` : text || "清空";
}

function sectionMatches(section: ConfigSection, query: string): boolean {
  if (!query) return true;
  return sectionOwnTextMatches(section, query) || section.fields.some((field) => fieldMatches(field, query));
}

function sectionOwnTextMatches(section: ConfigSection, query: string): boolean {
  if (!query) return true;
  return [section.title, section.description, section.key].some((value) => value.toLowerCase().includes(query));
}

function fieldMatches(field: ConfigField, query: string): boolean {
  if (!query) return true;
  return [field.label, field.description, field.path, field.env_name]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(query));
}

function draftStorageKey(scope: ConfigScope): string {
  return `${DRAFT_STORAGE_PREFIX}.${scope}`;
}

function restoreDraft(snapshot: ConfigSnapshot, scope: ConfigScope): { values: Record<string, DraftValue>; resets: Record<string, boolean>; savedAt: string } {
  const empty = { values: {}, resets: {}, savedAt: "" } as { values: Record<string, DraftValue>; resets: Record<string, boolean>; savedAt: string };
  try {
    const raw = window.sessionStorage.getItem(draftStorageKey(scope));
    if (!raw) return empty;
    const stored = JSON.parse(raw) as { revision?: string; values?: Record<string, DraftValue>; resets?: string[]; savedAt?: string };
    if (stored.revision !== snapshot.revision) {
      window.sessionStorage.removeItem(draftStorageKey(scope));
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
    window.sessionStorage.removeItem(draftStorageKey(scope));
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
  return error instanceof Error ? error.message : String(error);
}
