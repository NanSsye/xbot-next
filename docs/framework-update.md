# Docker 宿主机更新任务

适用 Linux、systemd、Python 3.11+、Docker CLI。执行器只管理名为 `xbot-pro` 且 `/app` 绑定到指定部署目录 `release/app` 的容器。不能在 Xbot 容器内运行，也不需要挂载 Docker socket。

安装一次：将宿主机脚本 `release_worker.py`、`release_switch.py` 和 `release_delta.py` 安装到 root 管理的 `/opt/xbot-updater/`，安装仓库提供的 systemd 服务。服务环境文件 `/etc/xbot-updater.env` 需设置 `XBOT_DEPLOY_ROOT`。使用 Compose 提供的 requests 和只读 status 挂载，旧容器首次增加挂载需要重新创建，不需要重建镜像。

发行工作站用 `scripts/build_web_delta.py OLD_DIST NEW_DIST OUTPUT_ZIP VERSION` 生成差异。两端必须来自官方构建。归档只包含 `delta.json` 和发生变化的文件，删除项不附内容；发行后对整个 ZIP 验签。宿主机在私有 `updater/payload` 暂存通过签名验证的文件，再原子发布清单到 `updater/approved.json`。不要从当前安装的可写代码自行生成可信基线。

只检查清单命中的本地冲突。用户确认后，停止目标服务，再逐个原子替换或删除；未变化的文件保留。新版健康检查失败时仅还原这批文件和版本标识，备份留在私有 updater 目录。断电中断须由运维检查，不能把任务当作成功或无条件重放。
