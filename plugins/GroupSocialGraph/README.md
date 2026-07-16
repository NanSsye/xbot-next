# GroupSocialGraph

发送“社交关系图”后，插件读取 xbot-next 统一会话存储中的近期群聊记录，计算直接互动关系并生成图片。

配置位于 `config.toml`。`admins = ["*"]` 允许所有群成员生成；生产环境建议填写管理员 wxid。

插件依赖 `Pillow` 和 `networkx`，并内置 Noto CJK 字体以确保 Docker 环境正确显示中文。
