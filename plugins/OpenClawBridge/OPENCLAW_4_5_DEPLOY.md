# OpenClawBridge OpenClaw 4.5 部署教程

本文用于把 `plugins/OpenClawBridge/openclaw` 这个 OpenClaw 端插件部署到别人机器上的 OpenClaw，并和 `869WXbot` 侧的 `OpenClawBridge` 插件打通。

## 1. 部署目标

完整链路是：

```text
微信 / 869WXbot
  -> plugins/OpenClawBridge/main.py
  -> WebSocket ws://<OpenClaw机器IP>:9093/ws
  -> OpenClaw wechat channel 插件
  -> OpenClaw agent
  -> WebSocket 回调
  -> 869WXbot 回发微信
```

本仓库里有两部分插件：

- `plugins/OpenClawBridge/`：装在 `869WXbot` 里的 Python 插件。
- `plugins/OpenClawBridge/openclaw/`：装在 OpenClaw 里的 TypeScript 插件，插件 ID 是 `wechat`。

## 2. 版本说明

用户口径里的 OpenClaw `4.5`，在 npm 包版本里应安装为：

```powershell
npm install -g openclaw@2026.4.5
```

原因是当前 OpenClaw npm 包采用类似 `2026.4.5` 的日期版本号，而不是 `4.5.0`。部署前建议先确认可安装版本：

```powershell
npm view openclaw versions --json
```

安装后确认版本：

```powershell
openclaw --version
```

如果输出不是 `2026.4.5`，先不要继续配置，避免后续插件 SDK 或配置结构不一致。

## 3. 安装 OpenClaw 4.5

OpenClaw 要求 Node.js 22 或更高版本。先检查：

```powershell
node -v
npm -v
```

Windows 可用：

```powershell
winget install OpenJS.NodeJS.LTS
```

Linux / WSL2 可用：

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
```

安装 OpenClaw 指定版本：

```powershell
npm install -g openclaw@2026.4.5
openclaw --version
```

首次安装后初始化 OpenClaw：

```powershell
openclaw onboard --install-daemon
openclaw doctor
openclaw status
```

如果是 Linux / WSL2，且出现 `openclaw: command not found`，检查 npm 全局路径是否在 `PATH`：

```bash
npm prefix -g
echo "$PATH"
```

## 4. 准备 OpenClaw 端插件目录

把本仓库的这个目录复制到 OpenClaw 机器上：

```text
Z:\869WXbot\plugins\OpenClawBridge\openclaw
```

建议复制成一个简单路径，例如：

Windows：

```text
C:\openclaw-plugins\wechat
```

Linux / WSL2：

```text
/opt/openclaw-plugins/wechat
```

复制后目录里至少应有：

```text
wechat/
  openclaw.plugin.json
  package.json
  index.ts
  src/
    accounts.ts
    allow-from.ts
    channel.ts
    config-schema.ts
    runtime.ts
```

`openclaw.plugin.json` 是 OpenClaw 原生插件的识别文件，不能漏。

## 5. 安装 OpenClaw 端插件

在 OpenClaw 机器上执行本地插件安装。

Windows 示例：

```powershell
openclaw plugins install C:\openclaw-plugins\wechat
openclaw plugins enable wechat
openclaw plugins inspect wechat
openclaw plugins list
```

Linux / WSL2 示例：

```bash
openclaw plugins install /opt/openclaw-plugins/wechat
openclaw plugins enable wechat
openclaw plugins inspect wechat
openclaw plugins list
```

如果安装时提示依赖缺失，进入插件目录安装依赖后再重试：

```powershell
cd C:\openclaw-plugins\wechat
npm install
openclaw plugins install C:\openclaw-plugins\wechat
```

插件的 `package.json` 目前只依赖 `ws`：

```json
{
  "dependencies": {
    "ws": "^8.18.3"
  }
}
```

## 6. 配置 OpenClaw 的 wechat channel

这个插件会在 OpenClaw gateway 进程里启动 WebSocket 服务，默认监听：

```text
ws://0.0.0.0:9093/ws
```

需要在 OpenClaw 配置里启用 `channels.wechat`。如果通过 OpenClaw Dashboard / setup wizard 配置，填这些值即可：

- `enabled`: `true`
- `wsHost`: `0.0.0.0`
- `wsPort`: `9093`
- `wsPath`: `/ws`
- `bridgeDownloadHost`: OpenClaw 机器能被 `869WXbot` 访问到的 IP，例如 `192.168.50.38`
- `defaultAccount`: `default`
- `accounts.default.enabled`: `true`

如果手动改 OpenClaw 配置，示例结构如下：

```json
{
  "channels": {
    "wechat": {
      "enabled": true,
      "wsHost": "0.0.0.0",
      "wsPort": 9093,
      "wsPath": "/ws",
      "bridgeDownloadHost": "192.168.50.38",
      "defaultAccount": "default",
      "accounts": {
        "default": {
          "name": "WeChat Bridge",
          "enabled": true
        }
      },
      "nonOwnerToolAuthMode": "deny",
      "nonOwnerToolAuthTools": ["exec", "bash", "shell"],
      "ownerExecBypassApproval": true,
      "nonOwnerSkillBlacklist": []
    }
  }
}
```

如果需要把微信消息路由到指定 agent，优先使用 OpenClaw 标准的 `bindings`。示例：

```json
{
  "bindings": [
    {
      "match": {
        "channel": "wechat",
        "accountId": "default"
      },
      "agent": "你的-agent-id"
    }
  ]
}
```

旧写法 `channels.wechat.accounts.default.agent` 仍有兼容逻辑，但插件源码里已经标记为 legacy fallback，建议只作为临时兜底。

## 7. 启动 OpenClaw gateway

重启 OpenClaw gateway，让插件真正启动监听：

```powershell
openclaw restart
openclaw status
openclaw logs --follow
```

日志里应能看到类似信息：

```text
[WeChat] Registering plugin package...
[WeChat] WS bridge listening at ws://0.0.0.0:9093/ws
```

如果看不到监听日志，重点检查：

- 插件是否已 `enable`。
- OpenClaw 是否启动的是 gateway 进程。
- `9093` 是否被别的进程占用。
- 防火墙是否允许 `9093/tcp` 入站。

Windows 查看端口：

```powershell
netstat -ano | findstr :9093
```

Linux 查看端口：

```bash
ss -lntp | grep 9093
```

## 8. 配置 869WXbot 侧 OpenClawBridge

编辑：

```text
plugins/OpenClawBridge/config.toml
```

关键项如下：

```toml
[openclaw]
ws_url = "ws://192.168.50.38:9093/ws"
account_id = "default"
download_base_url = "http://192.168.50.188:18790"
workspace_path = "../files"
```

需要替换：

- `ws_url`：改成 OpenClaw 机器的可访问 IP 和端口，例如 `ws://<OpenClaw机器IP>:9093/ws`。
- `account_id`：必须和 OpenClaw 配置里的 `channels.wechat.accounts` 键一致；上面的示例是 `default`。
- `download_base_url`：869WXbot 侧对外暴露 `/files/...` 的 HTTP 地址。当前仓库有 `OpenClawFileServer`，默认是 `http://<869WXbot机器IP>:18790`。
- `workspace_path`：保持 `../files` 即可，表示使用仓库根目录的 `files` 目录。

如果对方机器只需要纯文本收发，`download_base_url` 可以稍后再处理；如果要支持图片、文件、视频引用和回发，就必须让 OpenClaw 机器能访问这个 HTTP 地址。

## 9. 启用 869WXbot 侧插件

确认 `main_config.toml` 中 `disabled-plugins` 不包含：

```text
OpenClawBridge
OpenClawFileServer
```

当前仓库里 `OpenClaw` 旧插件可以保持禁用，因为这次使用的是 `OpenClawBridge`：

```toml
disabled-plugins = [
    "OpenClaw"
]
```

重启 869WXbot 后看日志，应出现：

```text
OpenClawBridge WS connecting: ws://<OpenClaw机器IP>:9093/ws
OpenClaw WS connected: ws://<OpenClaw机器IP>:9093/ws
OpenClaw WS registered with accountId: default
```

OpenClaw 侧日志也应出现：

```text
[WeChat] Bridge WS connected ...
[WeChat] Bridge registered: accountId=default ...
```

## 10. 联调验证

建议按这个顺序验证，定位最快：

1. 在 OpenClaw 机器上确认端口监听：

```powershell
netstat -ano | findstr :9093
```

2. 在 869WXbot 机器上测试能否访问 OpenClaw 端口：

```powershell
Test-NetConnection 192.168.50.38 -Port 9093
```

3. 重启 869WXbot，确认日志出现 `registered with accountId: default`。

4. 给微信机器人发触发词或 `@机器人`。

5. 看 OpenClaw 日志是否收到 `inbound_message` 并派发给 agent。

6. 看微信侧是否收到 OpenClaw 回复。

## 11. 常见问题

### 11.1 `bridge ws disconnected for account default`

说明 OpenClaw 端要回发消息时，找不到已注册的 869WXbot WebSocket。

处理：

- 检查 `plugins/OpenClawBridge/config.toml` 的 `account_id`。
- 检查 OpenClaw 配置的 `channels.wechat.accounts.default` 是否存在。
- 检查 869WXbot 日志是否已连接并注册。

### 11.2 869WXbot 一直连接失败

处理：

- 确认 OpenClaw gateway 已启动。
- 确认插件启用后监听 `9093`。
- 检查 `ws_url` 是否写成 `ws://<OpenClaw机器IP>:9093/ws`。
- 检查防火墙、安全组、Docker/WSL 网络转发。

### 11.3 文本能回，图片或文件失败

通常是 HTTP 文件地址互相访问不到。

处理：

- OpenClaw 机器要能访问 `download_base_url`。
- 869WXbot 机器要能访问 OpenClaw 插件暴露的 `/media/...` 地址。
- 确认 `OpenClawFileServer` 已启用并监听 `18790`。
- 浏览器或 `curl` 访问 `http://<869WXbot机器IP>:18790/healthz`。

### 11.4 OpenClaw 插件安装失败

处理：

- 确认安装路径指向包含 `openclaw.plugin.json` 的目录。
- 先执行 `npm install` 安装 `ws`。
- 执行 `openclaw plugins doctor`。
- 如果 OpenClaw 版本不是 `2026.4.5`，先统一版本再排查。

## 12. 交付给对方时的最小清单

给对方部署时，至少确认这些信息：

- OpenClaw 机器 IP：例如 `192.168.50.38`
- 869WXbot 机器 IP：例如 `192.168.50.188`
- OpenClaw 版本：`2026.4.5`
- OpenClaw WS：`ws://<OpenClaw机器IP>:9093/ws`
- WeChat accountId：`default`
- 869WXbot 文件服务：`http://<869WXbot机器IP>:18790`
- OpenClaw agent ID：用于 `bindings` 路由

## 13. 参考来源

- OpenClaw 安装文档：`https://open-claw.bot/docs/install/`
- OpenClaw Node.js 要求：`https://open-claw.bot/docs/install/node/`
- OpenClaw 插件 CLI 文档：`https://open-claw.bot/docs/cli/plugins/`
- 本仓库 OpenClaw 端插件：`plugins/OpenClawBridge/openclaw/openclaw.plugin.json`
- 本仓库 869WXbot 侧配置：`plugins/OpenClawBridge/config.toml`
