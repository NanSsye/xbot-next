import type { ChannelPlugin, OpenClawConfig } from "openclaw/plugin-sdk/core";
import {
    listWechatAccountIds,
    resolveDefaultWechatAccountId,
    resolveWechatAccount,
    type ResolvedWechatAccount,
} from "./accounts.js";
import { formatWechatAllowFromEntries } from "./allow-from.js";
import { getWechatRuntime, isBridgeConnected, sendToBridge } from "./runtime.js";

function buildOutboundFrame(event: "outbound_text" | "outbound_media", payload: Record<string, unknown>) {
    return {
        direction: "openclaw_to_bridge",
        event,
        payload,
        ts: Date.now(),
    };
}

import { WechatChannelConfigSchema } from "./config-schema.js";

type WechatToolAuthMode = "off" | "deny" | "approve";

export function getWechatToolAuthConfig(cfg: any): {
    mode: WechatToolAuthMode;
    tools: string[];
    ownerExecBypassApproval: boolean;
    skillBlacklist: string[];
} {
    const root = cfg?.channels?.wechat || {};
    const rawMode = typeof root.nonOwnerToolAuthMode === "string" ? root.nonOwnerToolAuthMode.trim().toLowerCase() : "off";
    const mode: WechatToolAuthMode = rawMode === "deny" || rawMode === "approve" ? rawMode : "off";
    const tools = Array.isArray(root.nonOwnerToolAuthTools)
        ? root.nonOwnerToolAuthTools
            .map((v: unknown) => String(v ?? "").trim())
            .filter(Boolean)
        : [];
    const skillBlacklist = Array.isArray(root.nonOwnerSkillBlacklist)
        ? root.nonOwnerSkillBlacklist
            .map((v: unknown) => String(v ?? "").trim().toLowerCase())
            .filter(Boolean)
        : [];
    const ownerExecBypassApproval = root.ownerExecBypassApproval === true;
    return { mode, tools, ownerExecBypassApproval, skillBlacklist };
}

type WechatChannelRoot = {
    wsHost?: string;
    wsPort?: number;
    wsPath?: string;
    bridgeDownloadHost?: string;
    defaultAccount?: string;
    accounts?: Record<string, {
        name?: string;
        enabled?: boolean;
        agent?: string;
    }>;
};

function getWechatChannelRoot(cfg: OpenClawConfig | Record<string, unknown> | undefined): WechatChannelRoot {
    return (((cfg as any)?.channels?.wechat) ?? {}) as WechatChannelRoot;
}

function isWechatConfigured(cfg: OpenClawConfig | Record<string, unknown> | undefined): boolean {
    const root = getWechatChannelRoot(cfg);
    return Boolean(
        (typeof root.wsHost === "string" && root.wsHost.trim()) ||
        root.wsPort != null ||
        (typeof root.wsPath === "string" && root.wsPath.trim()) ||
        (typeof root.bridgeDownloadHost === "string" && root.bridgeDownloadHost.trim()) ||
        (typeof root.defaultAccount === "string" && root.defaultAccount.trim()) ||
        (root.accounts && Object.keys(root.accounts).length > 0)
    );
}

function updateWechatConfig(
    cfg: OpenClawConfig,
    updates: {
        wsHost: string;
        wsPort: number;
        wsPath: string;
        bridgeDownloadHost: string;
        defaultAccount: string;
    },
): OpenClawConfig {
    const currentChannels = cfg.channels ?? {};
    const currentWechat = getWechatChannelRoot(cfg);
    return {
        ...cfg,
        channels: {
            ...currentChannels,
            wechat: {
                ...currentWechat,
                wsHost: updates.wsHost,
                wsPort: updates.wsPort,
                wsPath: updates.wsPath,
                bridgeDownloadHost: updates.bridgeDownloadHost,
                defaultAccount: updates.defaultAccount,
            },
        },
    };
}

const wechatSetupWizard = {
    channel: "wechat",
    getStatus: async ({ cfg }: { cfg: OpenClawConfig }) => {
        const configured = isWechatConfigured(cfg);
        return {
            channel: "wechat",
            configured,
            statusLines: [`WeChat: ${configured ? "configured" : "not configured"}`],
            selectionHint: configured ? "configured" : "not configured",
            quickstartScore: configured ? 1 : 0,
        };
    },
    configure: async ({
        cfg,
        prompter,
    }: {
        cfg: OpenClawConfig;
        prompter: {
            note: (message: string, title?: string) => Promise<void>;
            text: (params: {
                message: string;
                initialValue?: string;
                placeholder?: string;
                validate?: (value: string) => string | undefined;
            }) => Promise<string>;
        };
    }) => {
        const current = getWechatChannelRoot(cfg);
        await prompter.note(
            [
                "Configure the WeChat bridge connection used by the Web setup UI.",
                "These values control OpenClaw's bridge listener metadata.",
            ].join("\n"),
            "WeChat setup",
        );

        const wsHost = (
            await prompter.text({
                message: "WeChat WS host",
                initialValue: current.wsHost || "0.0.0.0",
                placeholder: "0.0.0.0",
                validate: (value) => (value.trim() ? undefined : "Host is required"),
            })
        ).trim();

        const wsPortRaw = (
            await prompter.text({
                message: "WeChat WS port",
                initialValue: String(current.wsPort || 9093),
                placeholder: "9093",
                validate: (value) => {
                    const parsed = Number.parseInt(value.trim(), 10);
                    return Number.isInteger(parsed) && parsed > 0 && parsed <= 65535
                        ? undefined
                        : "Enter a valid port";
                },
            })
        ).trim();

        const wsPathInput = (
            await prompter.text({
                message: "WeChat WS path",
                initialValue: current.wsPath || "/ws",
                placeholder: "/ws",
                validate: (value) => (value.trim() ? undefined : "Path is required"),
            })
        ).trim();
        const wsPath = wsPathInput.startsWith("/") ? wsPathInput : `/${wsPathInput}`;

        const bridgeDownloadHost = (
            await prompter.text({
                message: "Bridge download host",
                initialValue: current.bridgeDownloadHost || "127.0.0.1",
                placeholder: "127.0.0.1",
                validate: (value) => (value.trim() ? undefined : "Host is required"),
            })
        ).trim();

        const defaultAccount = (
            await prompter.text({
                message: "Default WeChat account",
                initialValue: current.defaultAccount || "default",
                placeholder: "default",
                validate: (value) => (value.trim() ? undefined : "Default account is required"),
            })
        ).trim();

        return {
            cfg: updateWechatConfig(cfg, {
                wsHost,
                wsPort: Number.parseInt(wsPortRaw, 10),
                wsPath,
                bridgeDownloadHost,
                defaultAccount,
            }),
        };
    },
};

export const wechatPlugin: ChannelPlugin<ResolvedWechatAccount> = {
    id: "wechat",
    meta: {
        id: "wechat",
        label: "WeChat",
        selectionLabel: "WeChat (Bridge WS)",
        docsPath: "/docs/channels/wechat",
        blurb: "Connect to WeChat via Python Bridge over WebSocket",
        showConfigured: true,
    },
    capabilities: {
        chatTypes: ["direct", "group"],
        media: true,
    },
    config: {
        listAccountIds: (cfg) => listWechatAccountIds(cfg),
        resolveAccount: (cfg, accountId) => resolveWechatAccount(cfg, accountId),
        defaultAccountId: (cfg) => resolveDefaultWechatAccountId(cfg),
        isConfigured: (_account, cfg) => isWechatConfigured(cfg),
        formatAllowFrom: ({ allowFrom }) => formatWechatAllowFromEntries(allowFrom),
        describeAccount: (account) => ({
            accountId: account.accountId,
            name: account.name,
            enabled: account.enabled,
            configured: true,
        }),
    },
    configSchema: WechatChannelConfigSchema,
    setupWizard: wechatSetupWizard,
    gateway: {
        startAccount: async (ctx) => {
            ctx.log?.info(`WeChat channel ${ctx.accountId} started. Waiting for WS bridge.`);
            while (!ctx.abortSignal.aborted) {
                await new Promise((r) => setTimeout(r, 1000));
            }
            return { ok: true };
        },
    },
    status: {
        buildAccountSnapshot: ({ account, runtime }) => {
            return {
                ...runtime,
                accountId: account.accountId,
                name: account.name,
                enabled: account.enabled,
                configured: true,
                running: true,
                connected: isBridgeConnected(account.accountId),
            };
        },
    },
    commands: {
        enforceOwnerForCommands: true,
        skipWhenConfigEmpty: true,
    },
    messaging: {
        targetResolver: {
            hint: "可使用 wxid_xxx、xxx@chatroom，或直接输入群名/备注",
            looksLikeId: (raw: string): boolean => {
                const trimmed = raw.trim();
                if (trimmed.startsWith("gh_")) return false;
                return true;
            },
        },
    },
    outbound: {
        deliveryMode: "direct",
        sendText: async ({ to, text, accountId, cfg, ...args }) => {
            const resolvedAccountId = resolveWechatAccount(cfg, accountId).accountId;
            const targets: string[] | undefined = (args as any).targets;
            const atWxids: string[] | undefined = (args as any).atWxids;
            // 如果有 targets 且目标是群聊，把 wxid 列表编码进正文末尾，供 aibot 提取
            let encodedText = text;
            const resolvedAtWxids = atWxids ?? targets;
            if (resolvedAtWxids && resolvedAtWxids.length > 0 && String(to).endsWith("@chatroom")) {
                encodedText = text + "\x01OCLAW_AT:" + resolvedAtWxids.join(",") + "\x01";
            }
            const payload = {
                type: "text",
                to,
                text: encodedText,
                accountId: resolvedAccountId,
                requestId: (args as any).requestId,
                atWxids: resolvedAtWxids,
            };
            const sent = sendToBridge(buildOutboundFrame("outbound_text", payload), resolvedAccountId);
            if (sent.ok) {
                return { ok: true, channel: "wechat", messageId: `msg-${Date.now()}` };
            }
            const errorMessage = "error" in sent ? sent.error : "bridge ws send failed";
            return { ok: false, error: new Error(errorMessage), channel: "wechat", messageId: "" };
        },
        sendMedia: async ({ to, mediaUrl, text, accountId, cfg, ...args }) => {
            const runtime = getWechatRuntime();
            const activeCfg = cfg ?? runtime.config.loadConfig();
            const resolvedAccountId = resolveWechatAccount(activeCfg, accountId).accountId;

            let resolvedUrl = mediaUrl;
            if (mediaUrl && !mediaUrl.startsWith("http://") && !mediaUrl.startsWith("https://")) {
                const wsRoot = (activeCfg?.channels?.wechat as {
                    wsPort?: unknown;
                    bridgeDownloadHost?: unknown;
                } | undefined) ?? {};
                const port = Number(wsRoot.wsPort || 9093);
                const host = wsRoot.bridgeDownloadHost || "127.0.0.1";

                let absolutePath = mediaUrl;
                if (!mediaUrl.startsWith("/")) {
                    const os = await import("os");
                    const path = await import("path");
                    const fs = await import("fs");
                    const workspaceDir = activeCfg?.agents?.defaults?.workspace || path.join(os.homedir(), ".openclaw", "workspace");
                    const candidates = [
                        path.join(workspaceDir, mediaUrl),
                        path.join(workspaceDir, "downloads", mediaUrl),
                        path.join("/tmp/openclaw", mediaUrl),
                        path.join("/tmp/openclaw/downloads", mediaUrl),
                    ];
                    for (const candidate of candidates) {
                        if (fs.existsSync(candidate)) {
                            absolutePath = candidate;
                            break;
                        }
                    }
                }

                const urlPath = absolutePath.startsWith("/") ? absolutePath.slice(1) : absolutePath;
                resolvedUrl = `http://${host}:${port}/media/${encodeURIComponent(urlPath).replace(/%2F/g, "/")}`;
            }

            const payload: any = {
                type: "media",
                to,
                mediaUrl: resolvedUrl,
                text,
                accountId: resolvedAccountId,
                requestId: (args as any).requestId,
                atWxids: (args as any).atWxids ?? (args as any).targets,
            };

            const sent = sendToBridge(buildOutboundFrame("outbound_media", payload), resolvedAccountId);
            if (sent.ok) {
                return { ok: true, channel: "wechat", messageId: `msg-${Date.now()}` };
            }
            const errorMessage = "error" in sent ? sent.error : "bridge ws send failed";
            return { ok: false, error: new Error(errorMessage), channel: "wechat", messageId: "" };
        },
    },
};
