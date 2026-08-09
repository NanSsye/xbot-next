import {
    type OpenClawConfig,
} from "openclaw/plugin-sdk/core";

const LOCAL_DEFAULT_ACCOUNT_ID = "default";

type WechatAccountConfig = Record<string, unknown> & {
    name?: string;
    enabled?: boolean;
    agent?: string;
};

type WechatChannelConfig = {
    accounts?: Record<string, unknown>;
};

type WechatChannelRoot = {
    defaultAccount?: unknown;
    accounts?: Record<string, unknown>;
};

function normalizeWechatAccountId(accountId?: string | null): string {
    const trimmed = typeof accountId === "string" ? accountId.trim().toLowerCase() : "";
    return trimmed || LOCAL_DEFAULT_ACCOUNT_ID;
}

export type ResolvedWechatAccount = {
    accountId: string;
    name: string;
    enabled: boolean;
    config: WechatAccountConfig;
};

function asObjectRecord(value: unknown): Record<string, unknown> | undefined {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        return undefined;
    }
    return value as Record<string, unknown>;
}

function getWechatAccounts(cfg: OpenClawConfig): Map<string, WechatAccountConfig> {
    const channelCfg = (cfg.channels?.wechat as WechatChannelConfig | undefined) ?? {};
    const accounts = asObjectRecord(channelCfg.accounts);
    const normalizedAccounts = new Map<string, WechatAccountConfig>();

    for (const [rawAccountId, rawAccount] of Object.entries(accounts ?? {})) {
        const accountId = normalizeWechatAccountId(rawAccountId);
        normalizedAccounts.set(accountId, (asObjectRecord(rawAccount) as WechatAccountConfig) ?? {});
    }

    return normalizedAccounts;
}

export function listWechatAccountIds(cfg: OpenClawConfig): string[] {
    const accountIds = [...getWechatAccounts(cfg).keys()].sort((left, right) => left.localeCompare(right));
    return accountIds.length > 0 ? accountIds : [LOCAL_DEFAULT_ACCOUNT_ID];
}

export function resolveDefaultWechatAccountId(cfg: OpenClawConfig): string {
    const accountIds = listWechatAccountIds(cfg);
    const channelRoot = (cfg.channels?.wechat as WechatChannelRoot | undefined) ?? {};
    const preferred =
        typeof channelRoot.defaultAccount === "string" && channelRoot.defaultAccount.trim()
            ? normalizeWechatAccountId(channelRoot.defaultAccount)
            : undefined;

    if (preferred && accountIds.includes(preferred)) {
        return preferred;
    }
    if (accountIds.includes(LOCAL_DEFAULT_ACCOUNT_ID)) {
        return LOCAL_DEFAULT_ACCOUNT_ID;
    }
    return accountIds[0] ?? LOCAL_DEFAULT_ACCOUNT_ID;
}

export function resolveWechatAccountConfig(
    cfg: OpenClawConfig,
    accountId?: string | null,
): WechatAccountConfig {
    const resolvedAccountId = accountId?.trim()
        ? normalizeWechatAccountId(accountId)
        : resolveDefaultWechatAccountId(cfg);
    return getWechatAccounts(cfg).get(resolvedAccountId) ?? {};
}

export function resolveWechatAccount(
    cfg: OpenClawConfig,
    accountId?: string | null,
): ResolvedWechatAccount {
    const resolvedAccountId = accountId?.trim()
        ? normalizeWechatAccountId(accountId)
        : resolveDefaultWechatAccountId(cfg);
    const account = resolveWechatAccountConfig(cfg, resolvedAccountId);
    const name = typeof account.name === "string" && account.name.trim()
        ? account.name.trim()
        : "WeChat";

    return {
        accountId: resolvedAccountId || LOCAL_DEFAULT_ACCOUNT_ID,
        name,
        enabled: account.enabled !== false,
        config: account,
    };
}

export function resolveWechatLegacyAgentId(
    cfg: OpenClawConfig,
    accountId?: string | null,
): string | undefined {
    const account = resolveWechatAccountConfig(cfg, accountId);
    const agentId = typeof account.agent === "string" ? account.agent.trim() : "";
    return agentId || undefined;
}
