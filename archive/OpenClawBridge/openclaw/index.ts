import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { Buffer } from "buffer";
import { createServer, type Server as HttpServer } from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import {
    emptyPluginConfigSchema,
    type OpenClawConfig,
    type OpenClawPluginApi,
} from "openclaw/plugin-sdk/core";
import { resolveWechatAccount, resolveWechatLegacyAgentId } from "./src/accounts.js";
import { isWechatOwner, resolveWechatOwnerAllowFrom } from "./src/allow-from.js";
import { getWechatToolAuthConfig, wechatPlugin } from "./src/channel.js";
import {
    getAllBridgeEntries,
    getBridgePongAt,
    getBridgeSocket,
    markBridgePong,
    registerBridgeSocket,
    removeBridgeSocket,
    setWechatRuntime,
    setWechatWsServer,
} from "./src/runtime.js";

let bridgeHttpServer: HttpServer | null = null;
let bridgeWss: WebSocketServer | null = null;
let bridgeHeartbeatTimer: NodeJS.Timeout | null = null;
let wechatInboxPruneTimer: NodeJS.Timeout | null = null;

const wechatGlobalState = ((globalThis as any).__openclawWechatPluginState ??= {
    bridgeStartupLogged: false,
    bridgeStartInProgress: false,
    bridgeStarted: false,
});

function resolveWechatWsConfig(cfg: any) {
    const root = cfg?.channels?.wechat || {};
    return {
        host: root.wsHost || "0.0.0.0",
        port: Number(root.wsPort || 9093),
        path: root.wsPath || "/ws",
    };
}

function buildFrame(direction: "openclaw_to_bridge", event: "ping" | "pong", payload: Record<string, unknown> = {}) {
    return {
        direction,
        event,
        payload,
        ts: Date.now(),
    };
}

/**
 * 获取 OpenClaw 允许的临时目录，确保媒体文件不会因为路径安全策略被拦截
 */
function getAllowedTmpDir(cfg?: any) {
    // 飞哥需求：微信入站的各种文件都落地到工作区临时目录，方便后续处理
    // 默认目录：<workspace>/tmp_trash/wechat_inbox
    try {
        const workspaceDir = cfg?.agents?.defaults?.workspace || path.join(os.homedir(), ".openclaw", "workspace");
        const inboxDir = path.join(workspaceDir, "tmp_trash", "wechat_inbox");
        if (!fs.existsSync(inboxDir)) {
            fs.mkdirSync(inboxDir, { recursive: true, mode: 0o700 });
        }
        return inboxDir;
    } catch {
        // ignore
    }

    // 回退：/tmp/openclaw (Linux 默认允许路径)
    const posixTmp = "/tmp/openclaw";
    try {
        if (os.platform() !== "win32") {
            if (!fs.existsSync(posixTmp)) {
                fs.mkdirSync(posixTmp, { recursive: true, mode: 0o700 });
            }
            return posixTmp;
        }
    } catch {
        // ignore
    }

    // Windows 或 权限不足时回退到默认
    return os.tmpdir();
}

function pruneOldFiles(rootDir: string, maxAgeMs: number, logger?: { info: (s: string) => void; warn: (s: string) => void }) {
    const now = Date.now();
    let removed = 0;

    const walk = (dir: string) => {
        let entries: fs.Dirent[];
        try {
            entries = fs.readdirSync(dir, { withFileTypes: true });
        } catch {
            return;
        }
        for (const ent of entries) {
            const full = path.join(dir, ent.name);
            try {
                const st = fs.statSync(full);
                if (ent.isDirectory()) {
                    walk(full);
                    // 尝试清理空目录
                    try {
                        const left = fs.readdirSync(full);
                        if (left.length === 0) fs.rmdirSync(full);
                    } catch {
                        // ignore
                    }
                    continue;
                }
                if (!st.isFile()) continue;
                if (now - st.mtimeMs > maxAgeMs) {
                    fs.unlinkSync(full);
                    removed += 1;
                }
            } catch {
                // ignore
            }
        }
    };

    walk(rootDir);
    if (removed > 0) {
        logger?.info?.(`[WeChat] pruned ${removed} old files under ${rootDir}`);
    }
}

function resolveWechatInboundRoute(api: OpenClawPluginApi, params: {
    cfg: OpenClawConfig;
    accountId: string;
    peer: { kind: "group" | "dm"; id: string };
}) {
    const routeInput = {
        cfg: params.cfg,
        channel: "wechat",
        accountId: params.accountId,
        peer: params.peer,
    } as const;
    const route = api.runtime.channel.routing.resolveAgentRoute(routeInput);
    const legacyAgentId = resolveWechatLegacyAgentId(params.cfg, params.accountId);

    if (!legacyAgentId || route.matchedBy !== "default" || legacyAgentId === route.agentId) {
        return route;
    }

    // Preserve legacy accounts.<id>.agent routing only when no standard binding matched.
    api.logger.warn(
        `[WeChat] channels.wechat.accounts.${params.accountId}.agent is deprecated; prefer bindings[].match.accountId instead.`,
    );

    return api.runtime.channel.routing.resolveAgentRoute({
        ...routeInput,
        cfg: {
            ...params.cfg,
            bindings: [
                ...(Array.isArray(params.cfg.bindings) ? params.cfg.bindings : []),
                {
                    agentId: legacyAgentId,
                    match: {
                        channel: "wechat",
                        accountId: params.accountId,
                    },
                },
            ],
        },
    });
}

async function handleInboundMessage(api: OpenClawPluginApi, body: any) {
    const timingStartedAt = Date.now();
    let timingLastAt = timingStartedAt;
    const requestIdForTiming = typeof body?.requestId === "string" ? body.requestId : "n/a";
    const logTiming = (stage: string) => {
        const now = Date.now();
        api.logger.info(
            `[WeChat] inbound timing requestId=${requestIdForTiming} stage=${stage} total=${now - timingStartedAt}ms delta=${now - timingLastAt}ms`,
        );
        timingLastAt = now;
    };
    // 优化日志显示：如果包含巨大的 base64 数据，在 log 中截断它
    const logBody = { ...body };
    if (logBody.media?.data) {
        logBody.media = { ...logBody.media, data: `[base64 data, length: ${logBody.media.data.length}]` };
    }
    if (typeof logBody.bridgePrompt === "string") {
        logBody.bridgePrompt = `[bridgePrompt length: ${logBody.bridgePrompt.length}]`;
    }
    if (typeof logBody.meta?.bridgePrompt === "string") {
        logBody.meta = {
            ...logBody.meta,
            bridgePrompt: `[bridgePrompt length: ${logBody.meta.bridgePrompt.length}]`,
        };
    }
    api.logger.info(`[WeChat] Inbound WS message: ${JSON.stringify(logBody)}`);
    logTiming("received");
    const { from, fromName, content, accountId, media, groupName, senderId, senderName, isGroup: isGroupPayload, requestId, replyContext, bridgePrompt, bridgePromptMode, meta } = body;

    const runtime = api.runtime;
    const cfg = runtime.config.loadConfig();
    const resolvedAccountId = resolveWechatAccount(cfg, accountId).accountId;
    logTiming("config_loaded");

    if (runtime.channel.activity?.record) {
        runtime.channel.activity.record({
            channel: "wechat",
            accountId: resolvedAccountId,
            direction: "inbound",
        });
    }

    if (!from || (!content && !media)) {
        throw new Error("Missing from or content/media");
    }

    let mediaPath: string | undefined;
    let mediaType: string | undefined;
    if (media) {
        try {
            if (media.data) {
                const buffer = Buffer.from(media.data, "base64");
                const filename = media.name || `msg-${Date.now()}.bin`;
                const tmpDir = getAllowedTmpDir(cfg);
                const dest = path.join(tmpDir, filename);
                fs.writeFileSync(dest, buffer);
                mediaPath = dest;
                mediaType = media.mime || "application/octet-stream";
            } else if (media.path && typeof media.path === "string") {
                if (media.path.startsWith("http://") || media.path.startsWith("https://")) {
                    const filename = media.name || `remote-${Date.now()}-${path.basename(new URL(media.path).pathname) || "file"}`;
                    const tmpDir = getAllowedTmpDir(cfg);
                    const dest = path.join(tmpDir, filename);
                    api.logger.info(`[WeChat] Downloading remote media: ${media.path} -> ${dest}`);
                    const response = await fetch(media.path);
                    if (response.ok) {
                        const buffer = Buffer.from(await response.arrayBuffer());
                        fs.writeFileSync(dest, buffer);
                        mediaPath = dest;
                        mediaType = media.mime || response.headers.get("content-type") || "application/octet-stream";
                    } else {
                        api.logger.error(`[WeChat] Failed to download remote media: ${response.statusText}`);
                    }
                } else {
                    mediaPath = media.path;
                    mediaType = media.mime || "application/octet-stream";
                }
            }
        } catch (err: any) {
            api.logger.error(`[WeChat] Media error: ${err.message}`);
        }
    }

    const isGroup = typeof isGroupPayload === "boolean" ? isGroupPayload : from.endsWith("@chatroom");
    const chatType = isGroup ? "group" : "direct";
    const messageId = body?.messageId ? String(body.messageId) : `msg-${Date.now()}`;

    // 统一落地：不管 bridge 给的是 base64、远程 URL，还是本地 path，最终都复制到工作区 wechat_inbox
    try {
        if (mediaPath && fs.existsSync(mediaPath)) {
            const inboxDir = getAllowedTmpDir(cfg);
            const ext = path.extname(mediaPath) || "";
            const safeExt = ext.length <= 12 ? ext : "";
            const dest = path.join(inboxDir, `${messageId}${safeExt || ""}`);
            if (dest !== mediaPath) {
                try {
                    fs.copyFileSync(mediaPath, dest);
                    mediaPath = dest;
                } catch {
                    // ignore
                }
            }
        }
    } catch {
        // ignore
    }
    logTiming("media_resolved");

    const resolvedSenderId = senderId || from;
    const resolvedSenderName = senderName || fromName || "User";

    const rawBody = typeof content === "string" ? content : "";
    const resolvedBridgePrompt = (
        typeof bridgePrompt === "string" && bridgePrompt.trim()
            ? bridgePrompt
            : typeof meta?.bridgePrompt === "string"
                ? meta.bridgePrompt
                : ""
    ).trim();
    const resolvedBridgePromptMode = (
        typeof bridgePromptMode === "string" && bridgePromptMode.trim()
            ? bridgePromptMode
            : typeof meta?.bridgePromptMode === "string"
                ? meta.bridgePromptMode
                : "body_for_agent"
    ).trim() || "body_for_agent";
    const baseBodyForAgent = mediaPath ? (rawBody ? `${rawBody}\n[media attached: ${mediaPath}]` : `[media attached: ${mediaPath}]`) : rawBody;
    const bodyForAgent = resolvedBridgePrompt && resolvedBridgePromptMode === "body_for_agent"
        ? `${resolvedBridgePrompt}\n\n[用户消息]\n${baseBodyForAgent}`
        : baseBodyForAgent;
    const wechatOwners = resolveWechatOwnerAllowFrom(cfg);
    const isCoreControlCommand = runtime.channel.commands.isControlCommandMessage(rawBody, cfg);
    logTiming("prompt_and_auth_prepared");

    if (
        isCoreControlCommand &&
        wechatOwners.length > 0 &&
        !isWechatOwner({
            cfg,
            senderId: resolvedSenderId,
            from,
            chatType,
        })
    ) {
        await wechatPlugin.outbound?.sendText?.({
            to: from,
            text: "该命令仅管理员可用。",
            accountId: resolvedAccountId,
            cfg,
        } as any);
        return;
    }

    const preRouteToolAuth = getWechatToolAuthConfig(cfg as any);
    const preRouteSenderIsOwner = isWechatOwner({
        cfg,
        senderId: resolvedSenderId,
        from,
        chatType,
    });
    const skillMatch = rawBody.match(/\/skill:([^\s]+)/i) || rawBody.match(/^\/([a-zA-Z0-9._-]+)/);
    const requestedSkillName = skillMatch?.[1] ? String(skillMatch[1]).trim().toLowerCase() : undefined;
    if (
        requestedSkillName &&
        !preRouteSenderIsOwner &&
        preRouteToolAuth.skillBlacklist.includes(requestedSkillName)
    ) {
        await wechatPlugin.outbound?.sendText?.({
            to: from,
            text: `这个 skill 仅主人可用：${requestedSkillName}`,
            accountId: resolvedAccountId,
            cfg,
        } as any);
        return;
    }

    const conversationLabel = isGroup ? (groupName || fromName || from) : resolvedSenderName;

    const peer = {
        id: from,
        kind: isGroup ? ("group" as const) : ("dm" as const),
    };
    const route = resolveWechatInboundRoute(api, {
        cfg,
        accountId: resolvedAccountId,
        peer,
    });
    const senderIsOwner = isWechatOwner({
        cfg,
        senderId: resolvedSenderId,
        from,
        chatType,
    });
    const wechatToolAuth = getWechatToolAuthConfig(cfg as any);
    const commandAuthorized = senderIsOwner;
    const ctxPayload = runtime.channel.reply.finalizeInboundContext({
        channel: "wechat",
        accountId: route.accountId,
        source: `wechat:${from}`,
        OriginatingChannel: "wechat",
        OriginatingTo: `wechat:${from}`,
        Provider: "wechat",
        Surface: "wechat",
        peer,
        author: {
            id: `wechat:${resolvedSenderId}`,
            name: resolvedSenderName,
            isBot: false,
        },
        ConversationLabel: conversationLabel,
        GroupSubject: isGroup ? (groupName || fromName || from) : undefined,
        SenderName: resolvedSenderName,
        SenderId: resolvedSenderId,
        MessageSid: messageId,
        MessageSidFull: messageId,
        From: from,
        To: route.accountId,
        isGroup,
        ChatType: chatType,
        AccountId: route.accountId,
        SessionKey: route.sessionKey,
        threadId: from,
        content: rawBody,
        Body: rawBody,
        BodyForAgent: bodyForAgent,
        RawBody: rawBody,
        CommandBody: rawBody,
        BridgePrompt: resolvedBridgePrompt || undefined,
        BridgePromptMode: resolvedBridgePrompt ? resolvedBridgePromptMode : undefined,
        CommandAuthorized: commandAuthorized,
        SenderIsOwner: senderIsOwner,
        senderIsOwner,
        OwnerAllowFrom: wechatOwners,
        ToolAuth: {
            sourceChannel: "wechat",
            sourceAccountId: route.accountId,
            sourceChatType: chatType,
            sourceChatId: from,
            sourceSenderId: resolvedSenderId,
            nonOwnerToolAuthMode: wechatToolAuth.mode,
            nonOwnerToolAuthTools: wechatToolAuth.tools,
            ownerExecBypassApproval: wechatToolAuth.ownerExecBypassApproval,
            nonOwnerSkillBlacklist: wechatToolAuth.skillBlacklist,
        },
        requestId,
        replyContext,
        MsgId: messageId,
        MediaPath: mediaPath,
        MediaType: mediaType,
        MediaPaths: mediaPath ? [mediaPath] : undefined,
        MediaUrls: (media && typeof media.path === "string" && media.path.startsWith("http")) ? [media.path] : undefined,
        MediaTypes: mediaType ? [mediaType] : undefined,
        // 标准补齐：Gemini 原生识别会用到上下文中的 Images 和 Files
        Images: mediaPath && mediaType?.startsWith("image/") ? [mediaPath] : undefined,
        Files: mediaPath ? [{
            path: mediaPath,
            mime: mediaType || "application/octet-stream",
            name: path.basename(mediaPath)
        }] : undefined,
        msg: {
            date: Date.now(),
            chat: { id: from, type: chatType },
            text: rawBody,
            from: { id: senderId || from, first_name: senderName || fromName || "User" },
        },
    });
    logTiming("context_finalized");

    const storePath = runtime.channel.session.resolveStorePath(cfg.session?.store, {
        agentId: route.agentId,
    });
    await runtime.channel.session.recordInboundSession({
        storePath,
        sessionKey: ctxPayload.SessionKey ?? route.sessionKey,
        ctx: ctxPayload,
        onRecordError: (err) => {
            api.logger.error(`[WeChat] Failed updating session meta: ${String(err)}`);
        },
    });
    logTiming("session_recorded");

    const dispatcher = runtime.channel.reply.createReplyDispatcherWithTyping({
        onTyping: async () => { },
    } as any);

    logTiming("dispatch_start");
    await runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher({
        ctx: ctxPayload,
        cfg,
        dispatcherOptions: {
            ...dispatcher,
            deliver: async (payload: any) => {
                const logText = (payload.text || "").substring(0, 100).replace(/\n/g, "\\n");
                api.logger.info(`[WeChat] Delivering reply to ${from} (${chatType}): text="${logText}..."`);

                const replyText = payload.text || "";
                const mediaRegex = /MEDIA:([^\s]+)/g;
                let cursor = 0;
                let match;
                const parsedMediaPaths = new Set<string>();

                while ((match = mediaRegex.exec(replyText)) !== null) {
                    const precedingText = replyText.substring(cursor, match.index).trim();
                    if (precedingText && wechatPlugin.outbound?.sendText) {
                        await wechatPlugin.outbound.sendText({
                            to: from,
                            text: precedingText,
                            accountId: route.accountId,
                            cfg,
                            requestId,
                            targets: payload.targets,
                        } as any);
                    }
                    const mPath = match[1];
                    if (mPath && !parsedMediaPaths.has(mPath)) {
                        parsedMediaPaths.add(mPath);
                        if (wechatPlugin.outbound?.sendMedia) {
                            await wechatPlugin.outbound.sendMedia({
                                to: from,
                                mediaUrl: mPath,
                                text: "",
                                accountId: route.accountId,
                                cfg,
                                requestId,
                            } as any);
                        }
                    }
                    cursor = match.index + match[0].length;
                }

                const remainingText = replyText.substring(cursor).trim();
                if (remainingText && wechatPlugin.outbound?.sendText) {
                    await wechatPlugin.outbound.sendText({
                        to: from,
                        text: remainingText,
                        accountId: route.accountId,
                        cfg,
                        requestId,
                        targets: payload.targets,
                    } as any);
                }

                const allMedia = [...(payload.mediaUrls || [])];
                if (payload.media && !allMedia.includes(payload.media)) allMedia.push(payload.media);
                for (const mUrl of allMedia) {
                    if (!parsedMediaPaths.has(mUrl)) {
                        parsedMediaPaths.add(mUrl);
                        if (wechatPlugin.outbound?.sendMedia) {
                            await wechatPlugin.outbound.sendMedia({
                                to: from,
                                mediaUrl: mUrl,
                                text: "",
                                accountId: route.accountId,
                                cfg,
                                requestId,
                            } as any);
                        }
                    }
                }
            },
        },
    });
    logTiming("dispatch_done");
}

const plugin = {
    id: "wechat",
    name: "WeChat",
    description: "WeChat channel plugin (WS bridge)",
    configSchema: emptyPluginConfigSchema(),
    register(api: OpenClawPluginApi) {
        try {
            setWechatRuntime(api.runtime);

            api.registerChannel({ plugin: wechatPlugin });

            if (api.registrationMode !== "full") {
                return;
            }

            const startBridge = async () => {
                const runtime = api.runtime;
                // Use process.argv to accurately detect if we are starting the gateway server.
                // This is more robust than runtime.mode in complex Docker shared network environments.
                const isStartingGateway = process.argv.includes("gateway");

                if (!isStartingGateway) {
                    return;
                }

                // Bridge startup must be idempotent: OpenClaw may load plugins multiple times during
                // gateway boot. Without this guard, we can crash with EADDRINUSE on the WS port.
                if (
                    wechatGlobalState.bridgeStartInProgress ||
                    wechatGlobalState.bridgeStarted ||
                    bridgeHttpServer ||
                    bridgeWss ||
                    bridgeHeartbeatTimer
                ) {
                    return;
                }
                wechatGlobalState.bridgeStartInProgress = true;

                if (!wechatGlobalState.bridgeStartupLogged) {
                    api.logger.info("[WeChat] Registering plugin package...");
                    wechatGlobalState.bridgeStartupLogged = true;
                }

                const cfg = runtime.config.loadConfig();
                const wsConfig = resolveWechatWsConfig(cfg);

                // 每天清理一次微信入站落地文件（默认保留 24h）
                if (!wechatInboxPruneTimer) {
                    const inboxDir = getAllowedTmpDir(cfg);
                    // 启动时先清理一遍，再每小时扫一次，效果等价于“每天清理”但更稳
                    pruneOldFiles(inboxDir, 24 * 60 * 60 * 1000, api.logger);
                    wechatInboxPruneTimer = setInterval(() => {
                        pruneOldFiles(inboxDir, 24 * 60 * 60 * 1000, api.logger);
                    }, 60 * 60 * 1000);
                }

                bridgeHttpServer = createServer((req, res) => {
                    // 简易文件服务：允许 aiBot 通过 HTTP 下载 OpenClaw 本地文件
                    // URL 格式：/media/<绝对路径>  例如 /media/root/.openclaw/workspace/cache/images/bird_1.png
                    if (req.url && req.url.startsWith("/media/")) {
                        const filePath = "/" + decodeURIComponent(req.url.slice("/media/".length));
                        try {
                            if (!fs.existsSync(filePath)) {
                                res.statusCode = 404;
                                res.end("File not found");
                                return;
                            }
                            const stat = fs.statSync(filePath);
                            if (!stat.isFile()) {
                                res.statusCode = 400;
                                res.end("Not a file");
                                return;
                            }
                            // 推断 MIME 类型
                            const ext = path.extname(filePath).toLowerCase();
                            const mimeMap: Record<string, string> = {
                                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
                                ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
                                ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                                ".pdf": "application/pdf", ".bin": "application/octet-stream",
                                // 文本和文档类型
                                ".md": "text/markdown", ".txt": "text/plain",
                                ".json": "application/json", ".xml": "application/xml",
                                ".csv": "text/csv", ".html": "text/html", ".htm": "text/html",
                                ".css": "text/css", ".js": "application/javascript",
                                // 压缩包
                                ".zip": "application/zip", ".rar": "application/x-rar-compressed",
                                ".7z": "application/x-7z-compressed", ".tar": "application/x-tar",
                                ".gz": "application/gzip",
                                // Office 文档
                                ".doc": "application/msword",
                                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                ".xls": "application/vnd.ms-excel",
                                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                ".ppt": "application/vnd.ms-powerpoint",
                                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            };
                            res.setHeader("Content-Type", mimeMap[ext] || "application/octet-stream");
                            res.setHeader("Content-Length", stat.size);
                            const stream = fs.createReadStream(filePath);
                            stream.pipe(res);
                        } catch (err: any) {
                            res.statusCode = 500;
                            res.end(`Error: ${err.message}`);
                        }
                        return;
                    }
                    res.statusCode = 404;
                    res.end("Not Found");
                });

                bridgeWss = new WebSocketServer({
                    server: bridgeHttpServer,
                    path: wsConfig.path,
                });
                setWechatWsServer(bridgeWss);

                bridgeWss.on("connection", (socket: WebSocket, req) => {
                    // Socket 尚未注册，等待 register 事件
                    let registeredAccountId: string | null = null;
                    api.logger.info(`[WeChat] Bridge WS connected from ${req.socket.remoteAddress || "unknown"}, awaiting register...`);

                    socket.on("message", async (raw) => {
                        try {
                            const text = typeof raw === "string" ? raw : raw.toString();
                            const frame = JSON.parse(text);
                            const event = frame?.event;

                            // 注册事件：客户端连上后发送 accountId 进行绑定
                            if (event === "register") {
                                const accountId = frame?.payload?.accountId;
                                if (!accountId || typeof accountId !== "string") {
                                    api.logger.warn("[WeChat] register event missing accountId, closing socket");
                                    socket.close(1008, "missing accountId in register");
                                    return;
                                }
                                registerBridgeSocket(accountId, socket);
                                registeredAccountId = accountId;
                                api.logger.info(`[WeChat] Bridge registered: accountId=${accountId} from ${req.socket.remoteAddress || "unknown"}`);
                                // 发送 pong 作为注册确认
                                socket.send(JSON.stringify(buildFrame("openclaw_to_bridge", "pong")));
                                return;
                            }

                            if (event === "ping") {
                                if (registeredAccountId) markBridgePong(registeredAccountId);
                                socket.send(JSON.stringify(buildFrame("openclaw_to_bridge", "pong")));
                                return;
                            }
                            if (event === "pong") {
                                if (registeredAccountId) markBridgePong(registeredAccountId);
                                return;
                            }
                            if (event === "inbound_message") {
                                // 如果消息中没有 accountId，用 register 时绑定的
                                const payload = frame?.payload || {};
                                if (!payload.accountId && registeredAccountId) {
                                    payload.accountId = registeredAccountId;
                                }
                                await handleInboundMessage(api, payload);
                                return;
                            }

                            api.logger.warn(`[WeChat] Unknown WS event: ${String(event)}`);
                        } catch (err: any) {
                            api.logger.error(`[WeChat] WS message handling failed: ${err.message}`);
                        }
                    });

                    socket.on("close", (code, reason) => {
                        if (registeredAccountId) {
                            // 只在当前 Socket 仍是该 accountId 的活跃连接时才移除
                            if (getBridgeSocket(registeredAccountId) === socket) {
                                removeBridgeSocket(registeredAccountId);
                            }
                        }
                        const reasonText = Buffer.isBuffer(reason) ? reason.toString("utf8") : String(reason || "");
                        api.logger.warn(`[WeChat] Bridge WS disconnected accountId=${registeredAccountId || "unregistered"} code=${code} reason=${reasonText || "n/a"}`);
                    });

                    socket.on("error", (err: any) => {
                        api.logger.error(`[WeChat] Bridge WS socket error (${registeredAccountId || "unregistered"}): ${err?.message || String(err)}`);
                    });
                });

                bridgeHttpServer.listen(wsConfig.port, wsConfig.host, () => {
                    wechatGlobalState.bridgeStarted = true;
                    api.logger.info(`[WeChat] WS bridge listening at ws://${wsConfig.host}:${wsConfig.port}${wsConfig.path}`);
                });

                // 心跳：遍历所有已注册的 Socket
                bridgeHeartbeatTimer = setInterval(() => {
                    for (const [accId, sock] of getAllBridgeEntries()) {
                        if (sock.readyState !== sock.OPEN) {
                            removeBridgeSocket(accId);
                            continue;
                        }
                        if (Date.now() - getBridgePongAt(accId) > 70000) {
                            api.logger.warn(`[WeChat] Bridge heartbeat timeout for accountId=${accId}, closing`);
                            sock.close(1001, "heartbeat timeout");
                            removeBridgeSocket(accId);
                            continue;
                        }
                        sock.send(JSON.stringify(buildFrame("openclaw_to_bridge", "ping")));
                    }
                }, 30000);
            };

            startBridge().catch(err => {
                api.logger.error(`[WeChat] Immediate bridge start failed: ${err.message}`);
            });
        } catch (err: any) {
            api.logger.error(`[WeChat] CRITICAL FAILURE during registration: ${err.message}`);
            if (err.stack) api.logger.error(err.stack);
        }
    },
};

export default plugin;
