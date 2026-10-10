# 卡片接入

固定模板位于 `backend/app/cards.py`，不使用环境变量。已在飞书卡片搭建工具核对线上版本：

| 操作 | 模板 ID | 固定版本 |
| --- | --- | --- |
| 加分 | `AAqzjRLLF2LbI` | `1.0.4` |
| 扣分 | `AAqzj4Y1vmkf7` | `1.0.3` |

五个变量均为**文本类型**：

| 变量 | 传入内容 |
| --- | --- |
| `department` | 记分对象完整部门路径，多部门去重后用中文分号连接；无部门时为“直属企业” |
| `user_name` | 记分对象姓名 |
| `reason` | 本次原因，保留换行 |
| `score` | 本次带符号分值转为字符串：加 5 分传 `"5"`，扣 5 分传 `"-5"` |
| `total_score` | 最终月度总分转为字符串，手动填写 `0` 传 `"0"` |

加分模板源码为 `+ ${score} 分`；扣分模板源码为 `${score} 分`，两者符号处理不同。操作人、月份和时间仅在操作台展示和账本保存，不加入模板变量。

机器人使用应用凭证获取 `tenant_access_token`，调用：

```http
POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id
Authorization: Bearer <tenant_access_token>
Content-Type: application/json; charset=utf-8
```

```json
{
  "receive_id": "ou_通知对象",
  "msg_type": "interactive",
  "content": "{\"type\":\"template\",\"data\":{\"template_id\":\"AAqzj4Y1vmkf7\",\"template_version_name\":\"1.0.3\",\"template_variable\":{\"department\":\"产研中心 / 智家产研部\",\"user_name\":\"测试员工\",\"reason\":\"专项延误\",\"score\":\"-5\",\"total_score\":\"55\"}}}",
  "uuid": "6215bffc-04a2-4eac-a167-8c020134de8a"
}
```

`content` 是 JSON 序列化后的**字符串**。代码负责转义，不手工拼接。每条投递使用稳定 UUID，1 小时内飞书去重；系统仅在 50 分钟内自动重试不确定结果。成功后保存 `data.message_id`。

预览、积分流水、后台发送共享同一份模板及变量快照；重试使用原快照。每位记分对象向每位通知对象独立私聊发送一张卡片。

真实联调前，确认应用已开启机器人、获得 `im:message:send_as_bot`、拥有两套模板使用权限，模板所有者和接收者在应用可用范围内。仅在操作台确认发送后才触发实际消息。

官方参考：[模板传值格式](https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json)、[发送消息接口](https://open.feishu.cn/document/server-docs/im-v1/message/create)。
