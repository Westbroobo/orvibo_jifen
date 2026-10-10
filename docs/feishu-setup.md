# 飞书应用配置与联调

使用同一企业自建应用完成登录、通讯录和机器人发送。初始管理员通过 `INITIAL_ADMIN_USER_IDS` 配置飞书 user_id，多个用英文逗号分隔；登录和消息发送所需的 open_id 由系统从当前应用同步获取。

## 应用后台

1. 开启网页应用及机器人能力。
2. 安全设置中的重定向 URL 与 `FEISHU_REDIRECT_URI` 完全一致；工作台入口填写 `PUBLIC_URL`。
3. 获取 App ID、App Secret 和企业 tenant_key，填写服务端环境变量。
4. 通讯录数据权限范围配置为全部成员，以便从根部门 `0` 遍历。应用可用范围包含全部预期通知接收者及卡片模板所有者；数据可读范围与机器人可发范围是两回事。
5. 发布并让管理员审批生效。没有分配本系统角色的员工仍不能执行记分操作。

## API 权限

本系统以 `tenant_access_token` 同步目录和发送消息，使用 `user_access_token` 仅完成登录身份读取。

通讯录最小字段权限建议：

- `contact:contact.base:readonly`：通讯录基本信息及事件。
- `contact:department.base:readonly`：部门名称和 ID。
- `contact:department.organize:readonly`：部门父子组织关系。
- `contact:user.base:readonly`：姓名、头像和基本信息。
- `contact:user.employee_id:readonly`：获取用户 user ID，用于匹配初始管理员。
- `contact:user.department:readonly`：人员所在部门列表。
- `contact:user.employee:readonly`：人员在职、离职等状态。

部分应用权限后台提供组合权限 `contact:contact:readonly_as_app`，可按后台与接口文档使用该只读组合。未获得状态字段的人员会保持待核实，不能加减分或通知。系统不需要手机号、邮箱、薪资等额外字段权限。

消息发送申请 `im:message:send_as_bot`。官方撤回接口支持这项权限，或 `im:message:recall`、`im:message` 中任一项，不需要额外申请读取消息权限。消息须由当前机器人发送，接收人仍在应用可用范围内，并符合企业设置的撤回时限。

登录使用 OAuth 授权码、PKCE S256 和一次性 state；服务端读取用户信息。无需申请 `offline_access`，不存储长期用户刷新令牌。

## 事件长连接

在“事件与回调”选择长连接接收方式，订阅：

- `contact.user.created_v3`
- `contact.user.updated_v3`
- `contact.user.deleted_v3`
- `contact.department.created_v3`
- `contact.department.updated_v3`
- `contact.department.deleted_v3`

由 worker 中的官方 `lark-oapi` SDK 建立连接，无需新增公开回调入口。事件处理在数据库提交后才返回，重复 event_id 去重。人员更新期间先阻止使用待核实人员，随后全量同步刷新。部署后需核对 SDK 连接日志和变更是否及时反映；每小时全量同步补偿事件遗漏。

## 两套卡片

两套模板及变量已固定在 `backend/app/cards.py`，无需环境变量配置：加分 `AAqzjRLLF2LbI` / `1.0.4`，扣分 `AAqzj4Y1vmkf7` / `1.0.3`。请在卡片搭建工具中授权积分系统的飞书应用使用这两套模板。版本升级需同步修改代码并重新部署，避免影响待确认预览。

网页预览对应绿色加分卡片和橙色扣分卡片，使用发送快照中的五个文本变量。操作人、月份和时间在卡片外展示。变量及发送请求格式见[卡片接入说明](card-templates.md)。

## 联调顺序

1. 手动执行 `database/schema.sql`（已有数据库仅执行新增增量段），再启动 API 和 worker；在 worker 日志确认全量同步完成。
2. 使用 `INITIAL_ADMIN_USER_IDS` 中对应的飞书账号登录，确认有管理员身份；该配置只用于初始化，已有管理员权限不会因修改配置而重置。
3. 在权限管理页核对部门路径、多部门归属和在职状态，给另一个测试账号分配操作员。
4. 使用测试人员和单个测试通知对象，分别检查加分、扣分模板；核对网页预览和真实卡片变量、总分。
5. 检查发送记录包含真实 `om_...` message ID。
6. 验证取消权限、调岗、离职后不能继续操作；通知范围配置跟随最新组织结构。
7. 在发送记录中申请整批或单条撤回，核对飞书卡片及撤回结果。系统只接受发送成功后 24 小时内的申请；企业撤回时限更短时，接口错误会显示在结果中。对应记分的全部通知撤回成功后，作废积分并重算该月余额；部分撤回、未发送、失败或待核实的通知仍使积分有效。流水及原卡片快照保留。

常见发送错误包括应用不可用、用户已离职、模板未发布、应用无模板权限和变量类型不匹配。修复配置后只重试明确失败的通知。不得为补发通知再次执行同一笔加减分。

更换飞书应用后，更新 `.env` 的 App ID 和 App Secret，并重启本地启动命令。新应用须重新配置登录回调、通讯录权限和全部成员数据范围、机器人、事件订阅及两套卡片的使用权限，发布后生效。

撤回使用 [DELETE /im/v1/messages/{message_id}](https://open.feishu.cn/document/server-docs/im-v1/message/delete)，整批逐条处理并记录结果。操作员只可撤回自己批次的卡片，管理员可处理全部批次。进程重启和网络超时会沿用同一 message_id 重试；接口返回已删除时记录撤回完成。撤回失败只重试撤回任务。

每位记分对象独立判断是否全部通知撤回成功，积分至多作废一次。该月从 60 分按原记账顺序重算剩余有效流水，手动总分覆盖仍作为后续起点；发送时总分及卡片内容不改写。旧批次的全部通知已经撤回成功时，worker 会自动补记作废，无需再次请求飞书撤回。

参考：[部门列表](https://open.feishu.cn/document/server-docs/contact-v3/department/children)、[部门直属人员](https://open.feishu.cn/document/server-docs/contact-v3/user/find_by_department)、[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[消息结构与卡片模板](https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json)、[OAuth 授权码](https://open.feishu.cn/document/authentication-management/access-token/obtain-oauth-code)。
