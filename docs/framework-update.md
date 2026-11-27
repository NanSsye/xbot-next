# Docker 宿主机更新任务

适用 Linux、systemd、Python 3.11+、Docker CLI。执行器只管理名为 `xbot-pro` 且 `/app` 绑定到指定部署目录 `release/app` 的容器。不能在 Xbot 容器内运行，也不需要挂载 Docker socket。

宿主机 Python 需要能导入 `cryptography`。从一个已验证的发行版本安装下列文件到 root 管理的 `/opt/xbot-updater/`，保留文件名，不要从容器内的可写代码目录加载这些模块：

- `scripts/` 中的 `release_worker.py`、`release_switch.py`、`release_delta.py`、`release_catalog.py`、`framework_stage.py` 和 `framework_manifest.py`。
- `src/xbot/services/release_signature.py` 以及经可信渠道核对的 `configs/release-signing.pub`。

安装仓库的 systemd 服务，环境文件 `/etc/xbot-updater.env` 设置 `XBOT_DEPLOY_ROOT`。使用 Compose 提供的 requests 和只读 status 挂载。旧容器首次增加挂载需要重新创建，不需要重建镜像。

正式发布时只上传一次 `scripts/framework_bundle.py` 从干净发行目录生成的签名完整包。宿主读取目录中的 `framework/xbot-framework`，验签目标清单，再下载需要的内容对象。客户端会生成私有的增量事务计划供执行器使用；这不是要求管理员按来源版本另行打包。

首次接入时将**对应旧官方发行包**中的签名 `release.json` 安装到宿主私有目录 `updater/baseline-<已安装标记>.json`。正常标记是此文件的 SHA-256。旧 Web 标记只有在签名清单中的 Web 清单指纹相同、且列出的非 Web 程序文件均与现场一致时才接受。找不到可信历史制品就停止；不要把用户当前目录签名当成官方旧版。成功更新会保留下次升级所需的新签名清单。当前自动切换只支持 `src/xbot/` 和 `ui/dist/` 的变化，依赖、迁移或运行时有变化的版本不得标为兼容直升。

只检查清单命中的本地冲突。用户确认后，停止目标服务，再逐个原子替换或删除；未变化的文件保留。新版健康检查失败时仅还原这批文件和版本标识，备份留在私有 updater 目录。断电中断须由运维检查，不能把任务当作成功或无条件重放。
