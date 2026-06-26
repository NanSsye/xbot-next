# Docker 本地构建运行

更新时间：2026-06-26

本项目支持用户在本机直接构建 Docker 运行环境，并把整个项目目录映射进容器。compose 会同时启动：

- `xbot` 后端和 Web 控制台
- 内置 `/files` 静态文件访问，用于 OpenClaw 拉取媒体
- PostgreSQL
- Redis

运行后，宿主机项目目录就是实际运行目录。用户后续升级时可以直接替换项目目录里的文件，然后重启 `xbot` 容器；一般不需要重新构建镜像。

## 环境要求

- Docker Engine 或 Docker Desktop
- 能访问 npm、PyPI；默认不下载 Playwright 浏览器

## 首次启动

```bash
cp .env.example .env
docker compose up -d --build
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

启动后访问：

```text
http://localhost:8548
```

局域网设备访问时，用运行 Docker 的电脑 IP：

```text
http://电脑局域网IP:8548
```

OpenClawBridge 媒体文件访问地址默认走同一个 xbot 应用，但用独立宿主机端口映射：

```text
http://电脑局域网IP:18790/files/文件名
```

compose 中 `18790:8548` 表示：宿主机 `18790` 转到容器内 xbot 的 `8548`，不是额外启动第二个文件容器。

## 持久化目录

compose 默认持久化到宿主机项目目录：

```text
./data/                  xbot 运行数据、媒体、Agent 文件
./data/hermes/           Hermes session、memory、skills、curator 状态和轨迹
./files/                 OpenClawBridge 对外发布的媒体文件，对应 /files URL
./logs/                  日志
./workspace/             Agent 工作目录
./ui/dist/               前端构建产物
./docker-data/postgres/  PostgreSQL 数据
./docker-data/redis/     Redis 数据
./docker-data/*          Docker 运行缓存
```

备份或迁移时，保留整个项目目录即可。不要删除 `docker-data/postgres`，否则数据库会丢失。

## 配置

Docker 运行时由 xbot 应用读取项目根目录 `/app/.env`，compose 不再用 `env_file` 把 `.env` 注入为容器环境变量。这样修改宿主机 `.env` 后，只需要重启容器，应用下次启动会重新读取文件：

```bash
docker compose restart xbot
```

常用配置：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.openai.com/v1
XBOT_LLM_MODEL=gpt-4.1-mini
XBOT_LLM_API_KEY=你的模型 key
```

内嵌 Hermes 会复用这些 `XBOT_LLM_*` 主模型配置。Hermes 自带扩展凭证不要写到根目录 `.env`；需要搜索、外部 memory provider、OpenRouter/Nous 等扩展时，放到 `data/hermes/.env`。

869 普通成员工具授权目录也写在根目录 `.env`：

```env
XBOT_WECHAT869_ADMIN_WXIDS=管理员wxid
XBOT_WECHAT869_MEMBER_WXIDS=
XBOT_WECHAT869_DEFAULT_PROFILE=member

XBOT_AGENT_MEMBER_POLICY_ENABLED=true
XBOT_AGENT_MEMBER_WORKSPACE_ROOTS=workspace,.agent-workspace
XBOT_AGENT_MEMBER_ALLOW_TERMINAL=true
XBOT_AGENT_MEMBER_ALLOW_PUBLIC_WEB=true
XBOT_AGENT_MEMBER_BLOCK_PRIVATE_NETWORK=true
```

Docker compose 会映射整个项目目录，所以相对授权目录就是容器内项目目录下的同名目录，同时也对应宿主机项目目录里的同名目录。例如 `workspace` 同时是：

```text
容器内：/app/workspace
宿主机：./workspace
```

不要把 `/`、`C:\`、`D:\` 或整个用户目录加入普通成员授权目录。

如果 869 运行在宿主机：

```env
XBOT_WECHAT869_HOST=host.docker.internal
XBOT_WECHAT869_WS_URL=ws://host.docker.internal:8848/ws/GetSyncMsg
```

如果它运行在局域网其他机器，改成对应机器 IP。

OpenClawBridge 插件不写在根目录 `.env`。启用后到插件配置里改：

```text
plugins/OpenClawBridge/config.toml
```

其中媒体下载地址应和 compose 的 `18790:8548` 映射一致：

```toml
[openclaw]
download_base_url = "http://你的机器IP:18790"
```

插件生成的 `/files/xxx` URL 会由 xbot 主应用内置静态路由提供，不需要单独的 `files` 容器。

## 常用命令

```bash
docker compose logs -f xbot
docker compose restart xbot
docker compose down
docker compose down -v
```

当前 compose 使用宿主机目录持久化。`docker compose down -v` 不会删除 bind mount 目录，但正常升级也不需要它。

## 升级

升级推荐方式：

```bash
git pull
docker compose restart xbot
```

如果用户不是 git 部署，而是下载压缩包部署：保留 `.env`、`data/`、`logs/`、`workspace/`、`docker-data/`，替换其他项目文件，然后执行：

```bash
docker compose restart xbot
```

当前 compose 默认关闭启动时重复安装依赖和重复构建前端：

```yaml
XBOT_DOCKER_INSTALL_DEPS_ON_START: "false"
XBOT_DOCKER_BUILD_UI_ON_START: "false"
```

依赖和前端在镜像构建阶段完成。数据库迁移仍按 `.env` 配置在启动时执行。
内嵌 Hermes 源码位于 `vendor/hermes/`。因为 compose 映射整个项目目录，替换 `vendor/hermes/` 后重启 `xbot` 容器即可生效；通常不需要重新构建镜像。

只有这些情况需要重新构建镜像：

- Dockerfile 改了
- Python/Node 系统运行环境要升级
- 需要重新安装 Playwright 浏览器系统依赖

重新构建命令：

```bash
docker compose up -d --build
```

## Agent 和 Playwright 可选依赖

默认镜像只安装通道、插件、API 和 Web 控制台所需依赖，不安装内置 Agent extra，也不下载 Playwright Chromium。

如果只使用 WeChat 869、OpenClawBridge 和普通插件，无需安装 Agent 依赖。

如果需要内置 Agent/Hermes 依赖，可在镜像或容器内安装：

```bash
pip install -e .[agent]
```

如果需要浏览器工具，再安装：

```bash
pip install -e .[browser]
python -m playwright install chromium
```

`INSTALL_PLAYWRIGHT=true` 只用于显式构建浏览器能力；默认保持 `false`，避免构建时下载 Chromium 卡住。
