import type { OpenClawConfig } from "openclaw/plugin-sdk/core";

const WECHAT_ALLOW_FROM_PREFIX_RE = /^(wechat|wx):/i;

function normalizeWechatAllowFromEntry(entry: string | number): string {
    const trimmed = String(entry).trim().toLowerCase();
    if (!trimmed) {
        return "";
    }
    return trimmed.replace(WECHAT_ALLOW_FROM_PREFIX_RE, "");
}

export function formatWechatAllowFromEntries(allowFrom: Array<string | number>): string[] {
    return allowFrom.map(normalizeWechatAllowFromEntry).filter(Boolean);
}

export function resolveWechatOwnerAllowFrom(cfg: OpenClawConfig): string[] {
    const raw = Array.isArray(cfg.commands?.ownerAllowFrom) ? cfg.commands.ownerAllowFrom : [];
    return formatWechatAllowFromEntries(raw);
}

export function isWechatOwner(params: {
    cfg: OpenClawConfig;
    senderId?: string | null;
    from?: string | null;
    chatType?: string | null;
}): boolean {
    const ownerAllowFrom = resolveWechatOwnerAllowFrom(params.cfg);
    if (ownerAllowFrom.includes("*")) {
        return true;
    }

    // Mirror the core owner matching shape closely enough for WeChat: prefer the
    // explicit sender id, and only fall back to `from` when the chat is direct.
    const rawCandidates: Array<string | number> = [];
    if (String(params.senderId ?? "").trim()) {
        rawCandidates.push(String(params.senderId));
    }
    if (
        rawCandidates.length === 0 &&
        String(params.from ?? "").trim() &&
        (params.chatType ?? "").trim().toLowerCase() === "direct"
    ) {
        rawCandidates.push(String(params.from));
    }

    const candidates = formatWechatAllowFromEntries(rawCandidates);
    return candidates.some((candidate) => ownerAllowFrom.includes(candidate));
}
