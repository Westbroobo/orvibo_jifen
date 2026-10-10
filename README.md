# ORVIBO_员工积分系统

公司内部加减分操作台，支持飞书登录、人员选择、权限管理及卡片通知。

发送记录支持整批或单条撤回：系统接受 24 小时内的申请，实际时限以企业飞书设置为准。同一笔记分的全部通知撤回成功后，积分作废并重算该月总分；部分撤回时积分仍有效，历史记录保留。

## 本地启动（Windows）

安装 Python 3.13、Node.js 24，将 `.env.example` 复制为 `.env`，填好 MySQL、飞书和初始管理员配置。先在数据库工具中手动执行 [database/schema.sql](database/schema.sql)：空库执行全文，已有数据库只执行末尾新增增量段。再在项目根目录运行：

```powershell
py -3.13 scripts\start-local.py
```

自动安装缺少的依赖，并在同一个终端启动 API、worker 和前端。访问 `.env` 中的 `PUBLIC_URL`，按 `Ctrl+C` 全部停止；修改 `.env` 后重新运行即可。

打开首页自动跳转飞书授权，授权后进入操作台；已有登录会话直接进入系统。

本地在 `.env` 填 `PUBLIC_URL=http://localhost:5174`、`FEISHU_REDIRECT_URI=http://localhost:5174/api/auth/callback`，飞书后台登记相同回调。前端端口从 `PUBLIC_URL` 读取，无需再传端口参数。脚本自动设置本地环境和 Cookie，不用填写 `APP_ENV` 或 `COOKIE_SECURE`。如需临时换端口，可加 `--port 5175 --api-port 8001`，并同步修改飞书后台回调。

## 服务器部署

1. 在腾讯云 MySQL 8 中创建空数据库 `jifen`，字符集使用 `utf8mb4`，手动执行 [database/schema.sql](database/schema.sql)；允许部署服务器连接，为应用账号授予读写权限。
2. 将 [.env.example](.env.example) 复制为 `.env`，按中文注释填写。`SESSION_SECRET` 可用 `openssl rand -hex 32` 生成；如果曾手动添加 `APP_ENV`、`COOKIE_SECURE`，部署时删除这两项以使用生产默认值。
3. 按[飞书配置清单](docs/feishu-setup.md)配置企业自建应用：网页登录、机器人、通讯录权限、可用范围和长连接事件订阅，并发布应用。
4. 在两套卡片的使用权限中添加该飞书应用。模板、版本和变量已固定在代码中，无需填写环境变量，详见[卡片接入说明](docs/card-templates.md)。
5. 在安装了 Docker Compose 的服务器上，于项目根目录执行：

```sh
docker compose up --build -d
```

6. 配置域名及 HTTPS 反向代理，转发到 `127.0.0.1:8080`。`PUBLIC_URL` 填该 HTTPS 地址；`FEISHU_REDIRECT_URI` 填该地址加 `/api/auth/callback`，并在飞书后台登记相同回调。
7. 等待首次人员同步后，用初始管理员的飞书账号登录，核对人员、分配操作员权限，先选少量通知对象完成预览和发送测试。

初始管理员在 `INITIAL_ADMIN_USER_IDS` 中填写**飞书 user_id**，人员同步后完成初始化；后续在系统权限页面管理。

查看运行日志：`docker compose logs -f api worker`。

数据库结构统一维护在 `database/schema.sql`：新数据库执行全文；已有数据库只执行末尾尚未应用的增量段。后续变更按日期追加，启动不会自动修改结构。

本次已有数据库执行末尾的“增量 2026-10-10（第二段）：撤回对应记分作废”整段；如果还没有 `message_recalls` 表，先执行上一段“消息撤回”。然后按 `Ctrl+C` 停止服务，重新运行上面的启动命令。worker 会补处理历史中全部通知已撤回成功的记分。
