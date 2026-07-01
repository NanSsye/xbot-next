# JaysonChatSummary for xbot-next

微信群聊总结插件。已适配当前 xbot-next 插件接口和主数据库。

## 功能

- 群内命令触发：`群聊总结`、`群聊总结 6小时`
- 从 xbot-next PostgreSQL 的 `conversation_messages` 读取真实聊天记录
- 使用 OpenAI-compatible / MiniMax-compatible LLM 生成结构化总结
- 使用 HTML 模板生成图片卡片并发送到群
- html2image 或 LLM 不可用时自动降级为文本总结
- 支持定时给多个群发送日报
- 保留多套 HTML 模板，支持随机模板

## 配置

编辑 `plugins/JaysonChatSummary/config.toml`：

- `minimax_base_url/minimax_api_key/minimax_model` 或 `openai_*`
- `html2image_url`：如 `http://127.0.0.1:8211/api/html2image`
- `target_groups`：定时发送群，如 `48587220177@chatroom`

## 触发

在微信群发送：

```text
群聊总结
群聊总结 12小时
```

## 商用注意

- 不提交真实 API Key。
- 生产环境建议配置稳定的 html2image 服务。
- 插件只总结数据库已有消息；若数据库未落库，不会凭空生成内容。
