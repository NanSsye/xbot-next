import type { ChannelConfigUiHint } from "openclaw/plugin-sdk/core";

const WECHAT_CONFIG_SCHEMA = {
    type: "object",
    properties: {
        enabled: { type: "boolean", description: "Whether the WeChat channel is enabled" },
        wsHost: { type: "string", description: "Bridge WS server host" },
        wsPort: { type: "number", description: "Bridge WS server port" },
        wsPath: { type: "string", description: "Bridge WS path" },
        bridgeDownloadHost: {
            type: "string",
            description: "HTTP host used when exposing local media files to the bridge",
        },
        defaultAccount: {
            type: "string",
            description: "Preferred default WeChat account for channel-level routing and fallback",
        },
        nonOwnerToolAuthMode: {
            type: "string",
            enum: ["off", "deny", "approve"],
            description: "Policy for non-owner sensitive tool use. deny = hard reject, approve = mark for approval flow, off = no extra gate",
        },
        nonOwnerToolAuthTools: {
            type: "array",
            items: { type: "string" },
            description: "Sensitive tool names protected by the non-owner policy",
        },
        ownerExecBypassApproval: {
            type: "boolean",
            description: "Best-effort hint that owner exec may bypass extra chat-side approval prompts",
        },
        nonOwnerSkillBlacklist: {
            type: "array",
            items: { type: "string" },
            description: "Skill names blocked for non-owner users; owner-only when matched",
        },
        accounts: {
            type: "object",
            additionalProperties: {
                type: "object",
                properties: {
                    name: { type: "string", description: "Display name for the WeChat account" },
                    enabled: { type: "boolean", description: "Whether this WeChat account is enabled" },
                    agent: {
                        type: "string",
                        description: "Legacy fallback agent id; prefer bindings[].match.accountId instead",
                    },
                },
            },
        },
    },
} as const;

export const wechatChannelConfigUiHints = {
    "": {
        label: "WeChat",
        help: "WeChat bridge configuration, account routing, and chat-side permission controls.",
    },
    enabled: {
        label: "WeChat Enabled",
        help: "Enable or disable the WeChat channel without removing its saved bridge settings.",
    },
    wsHost: {
        label: "WeChat WS Host",
        help: "Host address the WeChat bridge listener binds to.",
        placeholder: "0.0.0.0",
    },
    wsPort: {
        label: "WeChat WS Port",
        help: "Port used by the WeChat bridge WebSocket listener.",
        placeholder: "9093",
    },
    wsPath: {
        label: "WeChat WS Path",
        help: "HTTP path exposed by the bridge WebSocket server.",
        placeholder: "/ws",
    },
    bridgeDownloadHost: {
        label: "Bridge Download Host",
        help: "Host name or IP the bridge uses when OpenClaw exposes local media files over HTTP.",
        placeholder: "127.0.0.1",
    },
    defaultAccount: {
        label: "Default WeChat Account",
        help: "Preferred account id used when a request does not explicitly target a specific WeChat account.",
        placeholder: "default",
    },
    accounts: {
        label: "WeChat Accounts",
        help: "Per-account display names and enablement flags for each connected WeChat identity.",
        itemTemplate: {
            name: "",
            enabled: true,
            agent: "",
        },
    },
    nonOwnerToolAuthMode: {
        label: "Non-owner Tool Auth Mode",
        help: 'Extra approval policy for sensitive tool use by non-owner WeChat users: "off", "deny", or "approve".',
        advanced: true,
    },
    nonOwnerToolAuthTools: {
        label: "Protected Tool Names",
        help: "Tool names guarded by the non-owner policy above.",
        advanced: true,
        itemTemplate: "bash",
    },
    ownerExecBypassApproval: {
        label: "Owner Exec Bypass Approval",
        help: "Best-effort hint that owner exec requests may skip extra chat-side approval prompts.",
        advanced: true,
    },
    nonOwnerSkillBlacklist: {
        label: "Non-owner Skill Blacklist",
        help: "Skills blocked for non-owner WeChat users.",
        advanced: true,
        itemTemplate: "skill-name",
    },
} satisfies Record<string, ChannelConfigUiHint>;

export const WechatChannelConfigSchema = {
    schema: WECHAT_CONFIG_SCHEMA,
    uiHints: wechatChannelConfigUiHints,
};
