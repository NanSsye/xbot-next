# Docker 本地构建运行

本项目支持用户在本机直接构建 Docker 运行环境，并把整个项目目录映射进容器。compose 会同时启动：

- `xbot` 后端和 Web 控制台
- PostgreSQL
- Redis

运行后，宿主机项目目录就是实际运行目录。用户后续升级时可以直接替换项目目录里的文件，然后重启 `xbot` 容器；一般不需要重新构建镜像。

## 环境要求

- Docker Engine 或 Docker Desktop
- 能访问 npm、PyPI 和 Playwright 浏览器下载源

## 首次启动

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up -d --build
```

Windows PowerShell：

```powershell
Copy-Item .env.docker.example .env.docker
docker compose --env-file .env.docker up -d --build
```

启动后访问：

```text
http://localhost:8548
```

局域网设备访问时，用运行 Docker 的电脑 IP：

```text
http://电脑局域网IP:8548
```

## 持久化目录

compose 默认持久化到宿主机项目目录：

```text
./data/                  xbot 运行数据、媒体、Agent 文件
./logs/                  日志
./workspace/             Agent 工作目录
./ui/dist/               前端构建产物
./docker-data/postgres/  PostgreSQL 数据
./docker-data/redis/     Redis 数据
./docker-data/*          Docker 运行缓存
```

备份或迁移时，保留整个项目目录即可。不要删除 `docker-data/postgres`，否则数据库会丢失。

## 配置

Docker 使用 `.env.docker`。常用配置：

```env
XBOT_LLM_ENABLED=true
XBOT_LLM_PROVIDER=openai_compatible
XBOT_LLM_BASE_URL=https://api.openai.com/v1
XBOT_LLM_MODEL=gpt-4.1-mini
XBOT_LLM_API_KEY=你的模型 key
```

如果 869 或 OpenClaw 桥运行在宿主机：

```env
XBOT_WECHAT869_HOST=host.docker.internal
XBOT_WECHAT869_WS_URL=ws://host.docker.internal:8848/ws/GetSyncMsg
XBOT_OPENCLAW_BRIDGE_URL=http://host.docker.internal:1569
```

如果它们运行在局域网其他机器，改成对应机器 IP。

## 常用命令

```bash
docker compose logs -f xbot
docker compose --env-file .env.docker restart xbot
docker compose --env-file .env.docker down
docker compose --env-file .env.docker down -v
```

当前 compose 使用宿主机目录持久化。`docker compose down -v` 不会删除 bind mount 目录，但正常升级也不需要它。

## 升级

升级推荐方式：

```bash
git pull
docker compose --env-file .env.docker restart xbot
```

如果用户不是 git 部署，而是下载压缩包部署：保留 `.env.docker`、`data/`、`logs/`、`workspace/`、`docker-data/`，替换其他项目文件，然后执行：

```bash
docker compose --env-file .env.docker restart xbot
```

`xbot` 容器启动时会自动检查：

- `pyproject.toml` 变化：自动执行 `pip install -e .`
- `ui/` 前端源码变化：自动执行 `npm ci` 和 `npm run build`
- 数据库迁移：按 `.env.docker` 配置自动执行 Alembic migration

只有这些情况需要重新构建镜像：

- Dockerfile 改了
- Python/Node 系统运行环境要升级
- 需要重新安装 Playwright 浏览器系统依赖

重新构建命令：

```bash
docker compose --env-file .env.docker up -d --build
```

## 跳过 Playwright 浏览器安装

如果不需要浏览器截图/网页工具，可以在首次构建时跳过 Playwright 浏览器安装：

```bash
INSTALL_PLAYWRIGHT=false docker compose build
docker compose --env-file .env.docker up -d
```

Windows PowerShell：

```powershell
$env:INSTALL_PLAYWRIGHT="false"
docker compose build
docker compose --env-file .env.docker up -d
```
