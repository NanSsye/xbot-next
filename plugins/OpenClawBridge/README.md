# OpenClawBridge

`OpenClawBridge` 是一个基于 WebSocket 的 OpenClaw 微信桥接插件。

它会把当前框架收到的微信消息转发给 OpenClaw，并将 OpenClaw 返回的文本、图片、视频、语音、文件等内容回发到微信侧。

## 目录说明

- `main.py`：AllBot/869WXbot 侧插件实现
- `config.toml`：插件配置
- `openclaw/`：压缩包附带的 OpenClaw 侧 channel/plugin 参考实现

## 主要能力

- 维持到 OpenClaw 的 WS 长连接
- 转发私聊、群聊、@ 消息、引用消息
- 缓存图片/文件/视频等媒体，支持回调时再次发送
- 支持群聊白名单、黑名单、触发词与限流
- 支持 OpenClaw 回调文本、卡片、远程媒体、本地媒体路径

## 配置要点

编辑 [config.toml](/z:/869WXbot/plugins/OpenClawBridge/config.toml)：

- `openclaw.ws_url`：OpenClaw WS bridge 地址
- `openclaw.account_id`：桥接账号标识；留空时尝试使用机器人 wxid
- `openclaw.download_base_url`：文件下载基础地址
- `openclaw.workspace_path`：OpenClaw 工作区路径
- `prompt.enabled`：是否给每次转发到 OpenClaw 的消息附加桥接提示词
- `prompt.text`：桥接提示词内容；当前通过 OpenClaw 侧 `BodyForAgent` 注入，不改写 `RawBody`/`CommandBody`
- `filters.trigger_words`：触发转发的关键词
- `filters.filter_mode`：`None`、`Whitelist`、`Blacklist`
- `limits.*`：群聊限流配置

## 适配说明

本插件来自压缩包中的原始实现，已按当前仓库插件框架做了基础适配：

- 落入标准插件目录 `plugins/OpenClawBridge/`
- 保留 `__init__.py + main.py + config.toml` 结构
- 将 WS 连接启动迁移到插件启用/初始化阶段，避免在模块实例化时提前拉起后台任务
- 新增 `[basic] priority`，便于被当前插件管理器识别优先级
