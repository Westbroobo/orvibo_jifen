# ORVIBO_员工积分系统

公司内部加减分操作台，使用飞书登录并发送积分卡片。

## 本地启动（Windows）

安装 Python 3.13 和 Node.js 24，将 `.env.example` 复制为 `.env`，填写数据库、飞书及初始系统所有者配置。本地地址填写，并在飞书后台登记相同回调：

```dotenv
PUBLIC_URL=http://localhost:5174
FEISHU_REDIRECT_URI=http://localhost:5174/api/auth/callback
```

先在数据库工具中执行 [schema.sql](database/schema.sql)，再从项目根目录启动：

```powershell
py -3.13 scripts\start-local.py
```

脚本会安装缺少的依赖并启动前端、API 和 worker；按 `Ctrl+C` 停止。

## 服务器部署与更新

首次部署和 `.env` 配置见[部署说明](docs/deployment.md)。后续在服务器执行这一行即可拉取代码、构建镜像并重启容器：

```bash
cd /opt/orvibo_jifen && git pull --ff-only origin main && docker compose build api && docker compose build frontend && docker compose up -d --wait --wait-timeout 180
```

构建会复用已有依赖缓存。若更新包含数据库结构变更，先拉取代码，执行 `docker compose stop`，手动执行 [schema.sql](database/schema.sql) 末尾尚未应用的增量 SQL，再构建和启动容器。应用不会自动修改表结构。更新后可用 `docker compose ps` 查看容器状态。

本次权限升级执行第八段增量。`INITIAL_ADMIN_USER_IDS` 配置的在职员工会一次性成为系统所有者，可在“权限管理”配置角色、员工查看范围并查看变更记录；旧管理员与操作员的功能和范围保留。
