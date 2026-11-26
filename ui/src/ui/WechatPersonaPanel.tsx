import { Check, RotateCcw, Save, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { WechatConversation, WechatConversationPersona } from "../types";

type Props = {
  conversation?: WechatConversation;
};

export function WechatPersonaPanel({ conversation }: Props) {
  const [config, setConfig] = useState<WechatConversationPersona | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const conversationId = conversation?.id ?? "";
  const scopeLabel = conversation?.scope === "group" ? "本群" : "此私聊";
  const tooLong = prompt.length > 8000;

  useEffect(() => {
    const currentRequest = ++requestId.current;
    setNotice("");
    setError("");
    if (!conversationId) {
      setConfig(null);
      setEnabled(false);
      setModel("");
      setPrompt("");
      return;
    }

    setLoading(true);
    void api.wechatConversationPersona(conversationId)
      .then((next) => {
        if (requestId.current !== currentRequest) return;
        setConfig(next);
        setEnabled(next.enabled);
        setModel(next.model ?? "");
        setPrompt(next.prompt);
      })
      .catch((reason) => {
        if (requestId.current !== currentRequest) return;
        setError(reason instanceof Error ? reason.message : "读取会话配置失败");
      })
      .finally(() => {
        if (requestId.current === currentRequest) setLoading(false);
      });
  }, [conversationId]);

  async function save(nextEnabled = enabled, nextModel = model, nextPrompt = prompt) {
    if (!conversationId || saving || nextPrompt.length > 8000) return;
    if (nextEnabled && !nextPrompt.trim()) {
      setError(`启用${scopeLabel}专属人设前，请填写人设内容。`);
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await api.updateWechatConversationPersona(conversationId, {
        enabled: nextEnabled,
        prompt: nextPrompt.trim(),
        model: nextModel || null,
      });
      setConfig(next);
      setEnabled(next.enabled);
      setModel(next.model ?? "");
      setPrompt(next.prompt);
      setNotice("配置已保存，下一条消息立即生效。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存会话配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function resetSession() {
    if (!conversationId || saving) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api.resetWechatConversationPersonaSession(conversationId);
      setNotice("历史 Agent 会话已清空，下一条消息将使用当前配置。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重置 Agent 会话失败");
    } finally {
      setSaving(false);
    }
  }

  if (!conversation) {
    return <section className="wechat-persona-panel is-empty">选择会话后可配置独立人设与模型。</section>;
  }

  return (
    <section className="wechat-persona-panel" aria-busy={loading || saving}>
      <header className="wechat-persona-panel__head">
        <div>
          <span><Sparkles size={15} /> Agent 配置</span>
          <small>替换全局人设，并可覆盖默认模型</small>
        </div>
        <strong className={enabled || model ? "is-active" : ""}>
          {enabled || model ? `${scopeLabel}覆盖` : "继承全局"}
        </strong>
      </header>

      {loading ? <p className="wechat-persona-panel__hint">正在读取配置…</p> : (
        <div className="wechat-persona-panel__body">
          <label className="wechat-persona-switch">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            <span>使用{scopeLabel}专属人设</span>
          </label>

          <label htmlFor="wechat-persona-model">{scopeLabel}模型</label>
          <select id="wechat-persona-model" value={model} onChange={(event) => setModel(event.target.value)}>
            <option value="">继承全局默认 · {config?.default_model || "未设置"}</option>
            {(config?.enabled_models ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
          </select>

          <label htmlFor="wechat-persona-prompt">独立人设提示词</label>
          <textarea
            id="wechat-persona-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="填写后会直接替换全局人设，不会与全局内容叠加。"
            rows={7}
          />
          <div className={`wechat-persona-panel__meta ${tooLong ? "is-error" : ""}`}>
            <span>{prompt.length} / 8000</span>
            {config?.updated_at ? <span>已有已保存配置</span> : <span>尚未单独保存</span>}
          </div>

          <div className="wechat-persona-panel__feedback" aria-live="polite">
            {tooLong ? <span className="is-error">请删减 {prompt.length - 8000} 个字。</span> : null}
            {!tooLong && error ? <span className="is-error">{error}</span> : null}
            {!tooLong && !error && notice ? <span className="is-success"><Check size={13} />{notice}</span> : null}
          </div>

          <div className="wechat-persona-panel__actions">
            <button type="button" onClick={() => void resetSession()} disabled={saving}>
              <RotateCcw size={14} />重置会话
            </button>
            <button type="button" onClick={() => void save(false, "", "")} disabled={saving || (!config?.enabled && !config?.model && !config?.prompt)}>
              恢复全局
            </button>
            <button className="is-primary" type="button" onClick={() => void save()} disabled={saving || tooLong}>
              <Save size={14} />{saving ? "保存中" : "保存配置"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
