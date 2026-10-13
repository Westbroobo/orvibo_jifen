# Ubuntu 服务器部署

正式地址：`https://jifen.orvibo.com`。服务器已有 Docker 和 Compose，容器项目名为 `orvibo-jifen`。

已确认域名入口 `81.71.125.250` 向服务器 `10.1.255.35:8888` 发起连接；服务器公网 IP 为 `43.138.134.68`。新系统沿用旧系统的 `8888` 端口，绑定 `0.0.0.0` 接收网关回源。DNS 和现有 HTTPS 入口保持原配置，无需修改 Caddy。旧项目源码、两个容器及其 Compose 网络已删除。

## 1. 拉代码和配置

公开仓库直接拉取，服务器上执行：

```bash
git clone https://github.com/Westbroobo/orvibo_jifen.git /opt/orvibo_jifen
cd /opt/orvibo_jifen
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
nano .env
```

将生成的随机值填写到 `SESSION_SECRET`；按中文注释填好数据库、飞书应用及初始管理员。正式地址使用：

```dotenv
PUBLIC_URL=https://jifen.orvibo.com
FEISHU_REDIRECT_URI=https://jifen.orvibo.com/api/auth/callback
```

数据库继续使用腾讯云 MySQL 8，允许这台服务器连接。容器中的 `localhost` 指向容器本身，`DATABASE_URL` 的主机应填写实际数据库地址。

在数据库工具中执行 [schema.sql](../database/schema.sql)：新库执行全文，已有积分系统数据库只执行尚未应用的增量。应用启动不执行 DDL。若沿用本地开发已初始化的同一个云数据库，无需重新建表，员工和积分记录会继续保留。

飞书后台将网页登录回调登记为上面的 HTTPS 地址，应用入口填写 `https://jifen.orvibo.com`。机器人、通讯录权限、事件长连接和卡片授权按[飞书配置清单](feishu-setup.md)完成。

## 2. 启动容器

先确认入口端口未被占用：

```bash
ss -lnt 'sport = :8888'
```

在项目根目录运行。两个镜像依次构建，适合这台 2 核服务器：

```bash
docker compose config --quiet
docker compose build api && docker compose build frontend && docker compose up -d --wait --wait-timeout 180
docker compose ps
curl -fsS http://127.0.0.1:8888/api/health
```

健康接口应返回 `{"ok":true}`。API 和 worker 共用一个 Python 3.13 镜像；前端由 Node.js 24 构建，运行时使用 Nginx。服务器无需安装这两套运行环境。

| 服务 | 用途 | 内存上限 |
| --- | --- | --- |
| api | 登录、权限、积分和查询 | 512 MB |
| worker | 人员同步、事件长连接、发送及撤回 | 768 MB |
| frontend | 静态页面和 `/api/` 代理 | 128 MB |

仅前端映射宿主机端口；API 的 `8000` 在独立容器网络中，不影响服务器现有的 `8000`。容器自动重启，日志每个容器最多保留 3 个 10 MB 文件。所有业务数据在云数据库中。

## 3. 检查域名和登录

前端启动后，现有网关继续通过 `8888` 转发请求。检查正式域名：

```bash
curl -fsS https://jifen.orvibo.com/api/health
```

健康接口应与本机检查一致。若本机正常、域名仍返回 502，先查看 `docker compose logs --tail=100 frontend`，并用 `tcpdump -nn -i any 'tcp dst port 8888'` 检查网关回源；不要将端口改成仅绑定 `127.0.0.1`。

用初始管理员的飞书账号登录，核对首次人员同步和权限；用测试通知名单检查加分、扣分卡片及发送记录中的消息 ID。

## 更新及排查

常规代码更新：

```bash
cd /opt/orvibo_jifen
git pull --ff-only origin main
docker compose build api && docker compose build frontend && docker compose up -d --wait --wait-timeout 180
```

修改 `.env` 后用 `docker compose up -d --force-recreate --wait --wait-timeout 180` 重建容器以加载配置；无需重新构建镜像。若更新含数据库结构变更，先 `docker compose stop api worker`，手动执行新增 SQL，再启动。

```bash
docker compose ps
docker compose logs --tail=100 api worker frontend
docker compose logs -f api worker
```

若 API 不健康，先检查日志里的数据库连通性和 DDL 初始化结果；若登录正常但人员或通知异常，再检查 worker 日志及飞书配置。`up --wait` 等待 API 和前端健康，worker 的飞书连接及人员同步结果通过日志和权限页核对。
