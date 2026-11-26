# 005-wechat-workbench 技术方案（plan）：微信工作台 869 头像与机器人回复回显

> 关联 spec：[spec.md](./spec.md) | 最后更新：2026-11-26

## 方案
- **CRITICAL**：只以 869 发送结果确认出站，不用 Hermes 输出、`replies` 表或消息内容推断成功；线上实际回执待发布后验收。
- 当前反馈是 869 已有会话。联系人资料查询使用同版 Swagger 的批量接口；平台不给头像时保留首字。不会把通信凭据或资料原始回包写入实时出站事件。
- 复用 `ConversationRepository.append_message`、`message.created`、工作台的同步按钮及 CSS；运行时统一提交出站历史。升级后无迁移，回滚可恢复上一版本镜像，历史记录可保留。
- 图片仅沿用浏览器加载地址，不新增可访问的本地目录，也不让服务端代抓取。
- 同步响应增加 `private_avatars_received`，前端据此显示实际结果，保留原有计数字段。分两段修改：渠道与运行时确认发送，API 与工作台更新头像和反馈。

## 文件与图谱
| 文件 | 职责变化 |
| --- | --- |
| `ui/src/ui/App.tsx` | `page.wechat-workbench`：根据同步计数反馈，头像失败回退首字，沿用右侧气泡。 |
| `src/xbot/api/v1/wechat.py` | `api.wechat-workbench`：同步已知私聊联系人、隔离通道头像、复用运行时发送投影。 |
| `src/xbot/adapters/wechat869/client.py`、`src/xbot/adapters/wechat869/adapter.py` | `integration.wechat869-workbench`：按 Swagger 调联系人详情，校验并传递文字发送回执。 |
| `src/xbot/runtime/engine.py`、`src/xbot/runtime/context.py` | `service.wechat-workbench-outgoing`：接既有通知总线，成功后持久化出站并推送。 |
| `tests/integration/api/test_wechat_workbench.py` | 模拟 869 响应并验证持久化、实时事件及接口行为。 |

跨前端、联系人接口和出站链路分阶段修改，因此合计超过三个源文件，未添加依赖或修改数据表。
