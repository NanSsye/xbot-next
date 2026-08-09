import type { PluginRuntime } from "openclaw/plugin-sdk/core";
import type { WebSocket, WebSocketServer } from "ws";

let runtime: PluginRuntime | null = null;
let wsServer: WebSocketServer | null = null;

// accountId -> WebSocket
const bridgeSockets: Map<string, WebSocket> = new Map();
// accountId -> last pong timestamp
const bridgePongTimes: Map<string, number> = new Map();

function resolveBridgeAccountId(accountId?: string | null): string {
    const trimmed = typeof accountId === "string" ? accountId.trim().toLowerCase() : "";
    return trimmed || "default";
}

export function setWechatRuntime(next: PluginRuntime) {
    runtime = next;
}

export function getWechatRuntime(): PluginRuntime {
    if (!runtime) {
        throw new Error("WeChat runtime not initialized");
    }
    return runtime;
}

export function setWechatWsServer(server: WebSocketServer | null) {
    wsServer = server;
}

export function getWechatWsServer(): WebSocketServer | null {
    return wsServer;
}

/**
 * 注册 Bridge Socket，支持"喜新厌旧"：同 accountId 旧连接自动关闭
 */
export function registerBridgeSocket(accountId: string, socket: WebSocket) {
    const resolvedAccountId = resolveBridgeAccountId(accountId);
    const old = bridgeSockets.get(resolvedAccountId);
    if (old && old !== socket && old.readyState === old.OPEN) {
        try { old.close(1000, "replaced by new connection"); } catch { }
    }
    bridgeSockets.set(resolvedAccountId, socket);
    bridgePongTimes.set(resolvedAccountId, Date.now());
}

/**
 * 按 accountId 移除 Socket
 */
export function removeBridgeSocket(accountId: string) {
    const resolvedAccountId = resolveBridgeAccountId(accountId);
    bridgeSockets.delete(resolvedAccountId);
    bridgePongTimes.delete(resolvedAccountId);
}

/**
 * 按 accountId 获取 Socket
 */
export function getBridgeSocket(accountId: string): WebSocket | null {
    return bridgeSockets.get(resolveBridgeAccountId(accountId)) || null;
}

/**
 * 标记某个 account 的 pong 时间
 */
export function markBridgePong(accountId: string) {
    bridgePongTimes.set(resolveBridgeAccountId(accountId), Date.now());
}

/**
 * 获取某个 account 最后 pong 时间
 */
export function getBridgePongAt(accountId: string): number {
    return bridgePongTimes.get(resolveBridgeAccountId(accountId)) || 0;
}

/**
 * 判断某个 account 是否在线
 */
export function isBridgeConnected(accountId: string): boolean {
    const sock = bridgeSockets.get(resolveBridgeAccountId(accountId));
    return Boolean(sock && sock.readyState === sock.OPEN);
}

/**
 * 获取所有已注册的 [accountId, socket] 对，供心跳遍历
 */
export function getAllBridgeEntries(): [string, WebSocket][] {
    return Array.from(bridgeSockets.entries());
}

/**
 * 向指定 accountId 的 Bridge 发送消息
 */
export function sendToBridge(frame: unknown, accountId?: string): { ok: true } | { ok: false; error: string } {
    // 如果指定了 accountId，精准投递
    if (accountId) {
        const resolvedAccountId = resolveBridgeAccountId(accountId);
        const sock = bridgeSockets.get(resolvedAccountId);
        if (!sock || sock.readyState !== sock.OPEN) {
            return { ok: false, error: `bridge ws disconnected for account ${resolvedAccountId}` };
        }
        try {
            sock.send(JSON.stringify(frame));
            return { ok: true };
        } catch (err: any) {
            return { ok: false, error: err?.message || "bridge ws send failed" };
        }
    }

    // 未指定 accountId 时，回退：尝试发送给第一个可用的 socket（向后兼容）
    for (const [, sock] of bridgeSockets) {
        if (sock.readyState === sock.OPEN) {
            try {
                sock.send(JSON.stringify(frame));
                return { ok: true };
            } catch (err: any) {
                return { ok: false, error: err?.message || "bridge ws send failed" };
            }
        }
    }
    return { ok: false, error: "no bridge ws connected" };
}
