# aCode Remote

仅在 Telegram 私聊中提供聊天对象切换，并把选中的 aCode/Codex 任务排在
`agent_chat` 前处理。未选择 Codex 时，消息继续交给现有 Agent；QQ、微信和 TG
群聊不受影响。

## 工作方式

```text
Telegram 私聊 → xbot acode_remote → 电脑上的 aCode Gateway
                                     ↓
                              Codex app-server
```

xbot 服务器只连接 aCode Gateway。Codex 内部 `app-server` 必须继续监听
`127.0.0.1`，不要直接暴露到局域网或公网。

## 一、在运行 Codex 的 Windows 电脑安装 aCode

1. 从 [aCode Releases](https://github.com/BEelzebub594/aCode/releases) 下载最新的
   `aCode-server-windows-x64-*.zip`。
2. 解压后运行：

```powershell
.\acode-server.cmd init
.\acode-server.cmd doctor
.\acode-server.cmd start
```

Windows 发行包已内置 Node.js 和 SQLite，不需要修改电脑的全局 Node/npm。

首次初始化会创建：

```text
%APPDATA%\aCode-server\config.env
```

确认以下非敏感配置指向当前电脑：

```env
HOST=0.0.0.0
PORT=8787
PUBLIC_ORIGIN=http://电脑局域网IP:8787
CODEX_BIN=C:\Users\你的用户名\AppData\Roaming\npm\codex.cmd
CODEX_HOME=C:\Users\你的用户名\.codex
CODEX_APP_SERVER_PORT=8790
GATEWAY_ALLOWED_PATHS=D:\公司项目 D:\个人项目
```

`ADMIN_TOKEN` 和 `SESSION_SECRET` 使用 `init` 自动生成的随机值，不要复制到聊天、
日志或 xbot 根目录 `.env`。

本机验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/health
Invoke-RestMethod http://电脑局域网IP:8787/api/health
```

如果 xbot 在另一台服务器上，还要从服务器访问一次上述局域网地址。Windows 防火墙
放行时应只允许 xbot 服务器 IP 访问 TCP 8787，不要开放给整个公网。

### Windows 自动启动

优先使用发行包提供的 `install-service`：

```powershell
.\acode-server.cmd install-service
```

部分版本只会打印计划任务命令；没有管理员权限时，可以创建一个调用
`acode-server.cmd start` 的当前用户登录启动项。无论使用哪种方式，启动后都要重新
检查 8787 端口和 `/api/health`。

## 二、配置 xbot 插件

复制示例文件：

```powershell
Copy-Item plugins/acode_remote/config.example.toml plugins/acode_remote/config.toml
```

编辑插件自己的 `plugins/acode_remote/config.toml`：

```toml
[acode_remote]
enabled = true
base_url = "http://电脑局域网IP:8787"
admin_token = "填写 aCode config.env 中的 ADMIN_TOKEN"
allowed_user_ids = ["你的 Telegram 数字用户 ID"]
agent_label = "小X"
```

密钥只保存在这个插件文件中，不使用 xbot 根 `.env`。`config.toml` 已被本插件的
`.gitignore` 忽略，不能提交到 Git；Linux/NAS 上建议权限设为 `600`：

```bash
chmod 600 plugins/acode_remote/config.toml
```

配置文件必须是无 BOM 的 UTF-8。如果日志出现 `Invalid statement (at line 1,
column 1)`，重新保存为 UTF-8 without BOM。

配置完成后重载插件或重启 xbot：

```http
POST /api/v1/plugins/acode_remote/reload
```

日志应显示：

```text
[acode_remote] 已加载: enabled=True allowed_users=1 configured=True
```

## 三、Telegram 使用

- `/codex`、`/chat`：打开聊天对象菜单
- `/agent`：切回现有 Agent
- `/status`：查看当前聊天对象
- `/doctor`：检查 Telegram、aCode、Codex、任务恢复和语音组件状态
- `/stop`：停止当前 Codex 任务
- `/find 关键词`：按任务标题、项目名或路径搜索最近 100 个任务
- `/new 项目名 | 任务内容`：只在允许的项目目录中创建任务
- `/rename 新名称`：重命名当前任务
- `/archive`：二次确认后归档当前任务
- `/archived`：查看并恢复已归档任务

插件加载后会通过 Bot API 给 `allowed_user_ids` 中的管理员私聊注册上述精简命令，并把
聊天菜单按钮设为 `commands`。命令使用 `chat` 作用域，不会覆盖 TG 群聊或其他用户的
默认 Bot 命令；重启或重载插件后会自动恢复。

点击任务按钮后直接切换，不需要再次发送按钮文字。Codex 在后台执行时，不会阻塞
现有 Agent、QQ、微信或其他 TG 会话。

Codex 回复会自动转换成 Telegram HTML 富文本，支持标题、粗体、斜体、列表、引用、
安全链接、行内代码、代码块和表格转列表。长回复会在段落或代码块边界分段；运行时只
显示真实工具名称和状态，不显示命令、参数、输出、服务器路径或密钥。进度消息上的
“停止”按钮会携带当前 `turnId` 中断本轮，完成后按钮自动移除。Telegram 返回 429 时，
JSON 消息会按官方 `retry_after` 有限重试一次。

流式回复和工具状态始终编辑同一条运行卡片，不为每个片段新发消息。`/doctor` 只展示
必要的健康状态和耗时，不返回网关地址、目录或任何密钥；诊断卡可以点击按钮原地刷新。

从消息进入 Codex 到最终回复期间，插件每 4 秒续发一次 Telegram `typing` 状态，因此
聊天顶部会持续显示“正在输入”；最终回复、失败或停止后不再续发，并由 Telegram 自动
清除状态。

任务列表每行右侧的 `☆` 可以收藏任务，收藏结果保存在插件自己的 `data/favorites.json`，
以后会优先显示为 `★`。搜索结果也能直接切换或收藏，不需要退出当前分页。

### 从 Telegram 发送图片和文件给 Codex

选中一个空闲的 Codex 任务后，可以直接发送图片、文件、视频或语音，也可以在说明文字
中写处理要求。插件使用 Telegram 已下载的临时附件生成 aCode `attachments` 请求：

- 每次最多 8 个附件；
- 单个附件最大 15 MB；
- 图片会作为 Codex 本地图片输入；
- 普通文件由 aCode 保存到任务自己的 `.acode/attachments`；
- 不把 NAS 本地路径或 Base64 内容写入聊天和日志。

Telegram 相册会按 `media_group_id` 短暂合并，同一批图片只创建一个 Codex turn；相册
没有官方“发送结束”事件，因此插件在最后一个已收到的相册消息后默认等待 5 秒再提交。
进入 Codex 前，聊天顶部会按附件类型显示“正在上传照片 / 视频 / 语音 / 文件”，提交后
自动切换为“正在输入”。

aCode 当前的运行中插话接口只接受文字。因此任务正在运行时，文字仍可继续追加，附件会
明确提示等待本轮结束，不能把服务器路径伪装成电脑端文件。

Telegram 语音会在 xbot 服务器内通过 `faster-whisper` 本地转成文字，再交给 Codex；
语音内容不会发送到第三方转写接口。首次使用会下载配置的 Whisper 模型，默认是 `base`，
因此第一次回复会慢一些。语音暂时需要单独发送，不能和其他附件混在同一条消息。

插件每天只检查 Telegram 媒体目录和各任务自己的 `.acode/attachments/<threadId>`。
清理会先 dry-run 统计，再删除超过 30 天的文件，并跳过正在运行或等待审批的任务；不会
扫描或删除工作区中的其他文件。保留天数和开关都在插件自己的 `config.toml` 配置。

## 四、让 Codex 直接发送图片和文件

插件包含本机 STDIO MCP 工具 `send_to_telegram`。Codex 只需要传入明确的本机
文件路径，工具会自动上传到 xbot 服务器，并按扩展名选择 Telegram 图片或普通文件。
Bot Token 始终留在 xbot 服务器，不会进入本机 MCP 配置或工具返回值。

复制并编辑工具自己的配置：

```powershell
Copy-Item plugins/acode_remote/mcp_sender.example.toml plugins/acode_remote/mcp_sender.toml
```

配置 SSH 目标、服务器项目路径和容器名。该文件不包含 Telegram 密钥，并已被本插件
的 `.gitignore` 忽略：

```toml
[telegram_sender]
ssh_target = "root@192.168.1.100"
remote_project_dir = "/path/to/xbot-next"
container_name = "xbot-next-app"
max_file_mb = 49
timeout_seconds = 120
```

在运行 Codex 的电脑安装工具：

```powershell
codex mcp add telegram_sender -- uv run `
  --project "D:\公司项目\xbot-next" `
  --extra agent `
  python "D:\公司项目\xbot-next\plugins\acode_remote\mcp_server.py"
codex mcp list
```

Codex 桌面端、CLI 和 IDE 扩展会共享同一台 Codex 主机的 MCP 配置。新任务中可以直接
要求“把 `D:\项目\result.png` 发到 TG”。工具只发送本次明确指定的单个文件，限制
49 MB；服务器端只允许读取插件的临时发送目录。发送成功后立即删除中转文件；失败时
保留以便重试，并由 30 天附件维护统一清理。

## 任务管理与审批

新建任务只接受 aCode `GATEWAY_ALLOWED_PATHS` 中的目录，项目名必须唯一匹配；插件不接收
任意服务器路径。任务可以在 TG 中重命名、归档和恢复。搜索、任务列表和状态卡均使用原
消息编辑分页，避免反复刷屏。

TG 插件使用的 `/api/threads` 远程入口以 `approvalPolicy: never` 和
`danger-full-access` 启动任务，不再发送操作审批卡。这个模式可以直接联网和访问项目目录
外文件，因此必须保留 `allowed_user_ids` 私聊白名单，并限制 8787 端口只允许 xbot 服务器
访问。aCode 的 `/sessions` 兼容入口仍保持 `on-request` 和 `workspace-write`，不会把其他
客户端一起切换成完全模式。兼容旧版 aCode 运行进程时，插件会在后台自动允许审批事件，
不会向 TG 发送审批卡。连接或 Telegram 发送短暂失败时，待完成任务保存在
`data/pending_turns.json` 并每 10 秒恢复监听，重启后也会继续补发。

## 当前限制

同一个 Codex 任务不能同时被两个 `app-server` 写入。如果任务正在 Codex 桌面端中
运行，aCode 接管时会返回 `already has an active writer`。请先在电脑端释放该任务，
或者选择由 aCode 创建/接管的其他任务。插件会把这个错误转换成中文提示，不会把
原始英文错误直接发给 TG 用户。
