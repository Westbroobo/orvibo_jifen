# ORVIBO_员工积分系统

公司内部加减分操作台，支持飞书登录、人员选择、权限管理及卡片通知。

人员定时同步默认每天北京时间 02:00。管理员在“权限管理 → 同步设置”修改间隔天数和时间，或关闭定时同步；页面显示最近及下次同步时间。手动同步及飞书人员变更同步独立触发，不改变定时计划。

发送记录一行对应一次加减分操作，支持整批撤回。每位记分对象的全部通知撤回成功后，积分作废并重算该月总分；历史记录保留。

## 本地启动（Windows）

安装 Python 3.13、Node.js 24，将 `.env.example` 复制为 `.env`，填好 MySQL、飞书和初始管理员配置。先在数据库工具中手动执行 [database/schema.sql](database/schema.sql)：空库执行全文，已有数据库只执行末尾新增增量段。再在项目根目录运行：

```powershell
py -3.13 scripts\start-local.py
```

自动安装缺少的依赖，并在同一个终端启动 API、worker 和前端。访问 `.env` 中的 `PUBLIC_URL`，按 `Ctrl+C` 全部停止；修改 `.env` 后重新运行即可。

打开首页自动跳转飞书授权，授权后进入操作台；已有登录会话直接进入系统。

本地在 `.env` 填 `PUBLIC_URL=http://localhost:5174`、`FEISHU_REDIRECT_URI=http://localhost:5174/api/auth/callback`，飞书后台登记相同回调。前端端口从 `PUBLIC_URL` 读取，无需再传端口参数。脚本自动设置本地环境和 Cookie，不用填写 `APP_ENV` 或 `COOKIE_SECURE`。如需临时换端口，可加 `--port 5175 --api-port 8001`，并同步修改飞书后台回调。

## 服务器部署

服务器已安装 Docker Compose。按[部署说明](docs/deployment.md)拉取代码、填写 `.env`，在数据库工具中手动执行所需 DDL，再在项目根目录运行：

```sh
docker compose build api && docker compose build frontend && docker compose up -d --wait --wait-timeout 180
```

包含前端、API 和 worker 三个容器，仅前端入口监听 `8888`。沿用现有域名网关回源该端口，无需修改 DNS 或 Caddy；飞书回调登记 `https://jifen.orvibo.com/api/auth/callback`。服务器无需安装 Python 或 Node.js。

飞书权限及卡片授权见[飞书配置清单](docs/feishu-setup.md)。首次人员同步后，用 `INITIAL_ADMIN_USER_IDS` 中的飞书 **user_id** 对应账号登录，再分配操作员权限。

查看运行日志：`docker compose logs -f api worker`。

数据库结构统一维护在 [database/schema.sql](database/schema.sql)：新数据库执行全文；已有数据库按顺序执行尚未应用的末尾增量。最终 16 张表以 `orvibo_jifen_` 开头且不含外键，启动不会自动修改结构。

在“发送名单”维护个人名单，管理员还可维护所有操作员可选的公共名单。多个部门（含下级）和指定人员合并去重，使用时匹配最新在职人员；旧名单保留原部门交集规则。操作台选择名单即可，也可临时调整范围。

关联关系由后端在事务内校验，人员和业务历史只变更状态，不物理删除；主键和防重复的唯一索引保留。直接用数据库工具写入会绕过这些校验。
