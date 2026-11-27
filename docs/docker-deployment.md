# Docker 独立部署

这套配置供本地新版本验收和未来新实例使用，**不能用于覆盖旧实例**。
部署目录、Compose 项目、数据库和卷必须和旧实例分开。

## 构建与运行

构建机按目标平台构建并导出镜像（生产发布需先通过镜像实机验收）：

镜像使用 Python 3.14 与 `uv.lock`，构建时下载并校验固定 Hermes `v0.23.4`；部署端不需要源码或联网下载 Hermes。若升级独立实例，先备份 `state/data/hermes/`，不要用旧版打开已升级的状态库。

```sh
docker build --platform linux/amd64 -t xbot-next:clean-local .
docker save xbot-next:clean-local -o xbot-next-clean-local.tar
```

部署机仅需要镜像包、`docker-compose.yml` 和独立的 `.env`。加载镜像后创建本地配置；示例中的密钥均为空：

- `XBOT_IMAGE`：已加载的镜像标签，例如 `xbot-next:clean-local`。
- `XBOT_LAN_IP`：宿主机可信局域网 IP，仅本机使用时填 `127.0.0.1`。局域网默认免登录；已启用认证的实例应保留 `XBOT_API_AUTH_ENABLED=true` 与已有 Token。
- `XBOT_POSTGRES_PASSWORD`：新的 URL 安全随机密码，例如通过 `openssl rand -hex 32` 生成。
- 模型参数用 `XBOT_LLM_*` 配置，通道凭据只在需要时单独设定。不要复用旧实例的 `.env`。

```sh
docker load -i xbot-next-clean-local.tar
docker compose config --quiet
docker compose up -d
```

默认入口为 `http://<XBOT_LAN_IP>:18548`。不要转发至公网。首次启动按镜像内容初始化完整宿主机 `release/app/`，包含 `.venv` 和前端产物。非空目录不会被覆盖；已有部署迁移前先备份，确认原认证设置与网络边界。
不转发 PostgreSQL 或 Redis 端口，不在容器启动时重新安装依赖或构建 UI。

## 持久化与升级

`state/data/` 保存网页配置、Hermes 会话与产物；`state/logs/`、`state/files/` 和 `state/workspace/` 分别保存日志、发布文件和工作区。
PostgreSQL、Redis 使用 Compose 项目的独立命名卷。备份时保留独立 `.env`、`state/`、PostgreSQL 数据及 Redis 持久化文件，保护凭据和会话数据。

新版本首次启动会执行 `fresh_0001`。它不会创建微伴社区表，也不能识别旧实例的 Alembic 版本。
备份应包含完整 `release/app/`。修改映射中的兼容代码后重启应用即可；单独更换镜像不会替换宿主机已有代码。不要删除命名卷，也不要对实际使用的数据库运行初始迁移的 downgrade。
