from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, new_id, now_utc


class SystemState(Base):
    __tablename__ = "system_state"
    __table_args__ = {"comment": "系统运行状态与组织同步控制（固定单行）"}
    id: Mapped[int] = mapped_column(primary_key=True, comment="状态记录主键，固定为 1")
    directory_version: Mapped[int] = mapped_column(default=0, comment="组织架构版本号，用于同步并发校验")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近一次成功同步时间（UTC）")
    last_sync_error: Mapped[str | None] = mapped_column(Text, comment="最近一次组织同步错误，成功后清空")
    sync_requested: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否待执行全量组织同步")
    sync_started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="当前同步任务开始时间（UTC），用于防止重复执行")
    bootstrap_done: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已完成初始管理员权限初始化")
    events_connected_at: Mapped[datetime | None] = mapped_column(DateTime, comment="飞书事件长连接最近重连成功时间（UTC），断开时清空")


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = {"comment": "员工基本信息、飞书身份与操作权限"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, comment="系统内部员工 ID（UUID）")
    open_id: Mapped[str] = mapped_column(String(100), unique=True, comment="员工在当前飞书应用中的 open_id，用于登录及消息发送")
    user_id: Mapped[str | None] = mapped_column(String(100), unique=True, comment="飞书企业内 user_id，用于匹配初始管理员")
    name: Mapped[str] = mapped_column(String(200), comment="员工姓名")
    avatar_url: Mapped[str] = mapped_column(Text, default="", comment="员工头像地址")
    status: Mapped[str] = mapped_column(String(20), default="unknown", comment="人员状态：active 在职可用，resigned 离职，inactive 冻结或退出，unknown 待核实")
    role: Mapped[str] = mapped_column(String(20), default="none", comment="系统角色：admin 管理员，operator 操作员，none 未授权")
    feishu_status: Mapped[dict] = mapped_column(JSON, default=dict, comment="飞书通讯录返回的原始人员状态")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="人员信息最近更新时间（UTC）")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = {"comment": "飞书部门目录及完整层级路径"}
    id: Mapped[str] = mapped_column(String(100), primary_key=True, comment="飞书部门 open_department_id")
    name: Mapped[str] = mapped_column(String(200), comment="部门名称")
    parent_id: Mapped[str] = mapped_column(String(100), default="0", comment="上级部门 open_department_id，0 表示根节点")
    path_ids: Mapped[list] = mapped_column(JSON, default=list, comment="从一级部门到当前部门的完整部门 ID 数组")
    path_names: Mapped[list] = mapped_column(JSON, default=list, comment="从一级部门到当前部门的完整部门名称数组")
    active: Mapped[bool] = mapped_column(Boolean, default=True, comment="部门是否在最近一次完整同步范围内有效")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = {"comment": "员工与部门的多对多归属关系"}
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), primary_key=True, comment="系统内部员工 ID，关联 employees.id")
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), primary_key=True, comment="所属部门 ID，关联 departments.id")


class Preset(Base):
    __tablename__ = "presets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, comment="个人发送配置 ID（UUID）")
    owner_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, comment="配置所属员工 ID，仅本人可访问")
    name: Mapped[str] = mapped_column(String(100), comment="配置名称，同一用户下不可重复")
    selection: Mapped[dict] = mapped_column(JSON, comment="通知范围条件：部门层级、选择模式、勾选人员及额外人员")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="配置最近更新时间（UTC）")
    __table_args__ = (UniqueConstraint("owner_id", "name"), {"comment": "用户私有的通知范围配置"})


class Balance(Base):
    __tablename__ = "balances"
    __table_args__ = {"comment": "员工月度积分余额，每人每月唯一"}
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), primary_key=True, comment="记分员工 ID，关联 employees.id")
    month: Mapped[str] = mapped_column(String(7), primary_key=True, comment="北京时间自然月，格式 YYYY-MM")
    total: Mapped[int] = mapped_column(Integer, default=60, comment="本月当前最终总分，无记录时以 60 分为起点")
    version: Mapped[int] = mapped_column(Integer, default=0, comment="余额版本号，每次记账递增，用于预览并发校验")


class Preview(Base):
    __tablename__ = "previews"
    __table_args__ = {"comment": "积分操作预览凭据与内容快照"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="预览凭据的 SHA-256 摘要，不保存原始凭据")
    owner_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), comment="创建预览的操作员 ID")
    request: Mapped[dict] = mapped_column(JSON, comment="预览请求：记分对象、分值、原因、覆盖总分及通知范围")
    snapshot: Mapped[dict] = mapped_column(JSON, comment="预览计算结果快照，含逐人总分、余额版本、卡片及通知名单")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="预览创建时间（UTC）")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, comment="预览到期时间（UTC），创建后 10 分钟")
    batch_id: Mapped[str | None] = mapped_column(String(36), comment="确认后关联的记账批次 ID，未确认时为空")


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, comment="积分操作批次 ID（UUID）")
    operator_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, comment="执行本次操作的员工 ID")
    idempotency_key: Mapped[str] = mapped_column(String(100), comment="客户端提交幂等键，同一操作员下唯一，防止重复记账")
    preview_id: Mapped[str] = mapped_column(String(64), unique=True, comment="所用预览凭据摘要，确保一个预览只记账一次")
    month: Mapped[str] = mapped_column(String(7), comment="北京时间记分自然月，格式 YYYY-MM")
    delta: Mapped[int] = mapped_column(Integer, comment="本次积分变动值，正数加分，负数扣分，不能为 0")
    reason: Mapped[str] = mapped_column(Text, comment="加分或扣分原因，同批次所有记分对象共用")
    snapshot: Mapped[dict] = mapped_column(JSON, comment="确认时的完整预览快照，保留人员、总分、卡片及通知名单")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True, comment="批次记账时间（UTC）")
    __table_args__ = (UniqueConstraint("operator_id", "idempotency_key"), {"comment": "已确认的积分操作批次与幂等记录"})


class Ledger(Base):
    __tablename__ = "ledger"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, comment="积分流水 ID（UUID）")
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True, comment="所属操作批次 ID，关联 batches.id")
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), comment="本条流水的记分员工 ID")
    month: Mapped[str] = mapped_column(String(7), comment="北京时间记分自然月，格式 YYYY-MM")
    delta: Mapped[int] = mapped_column(Integer, comment="本次积分变动值，正数加分，负数扣分")
    before_total: Mapped[int] = mapped_column(Integer, comment="操作前本月总分，月内首次记账为 60 分")
    final_total: Mapped[int] = mapped_column(Integer, comment="本次操作后的最终总分，作为后续记账起点")
    override_total: Mapped[int | None] = mapped_column(Integer, comment="用户手动覆盖的最终总分，空表示自动计算，0 为有效值")
    card: Mapped[dict] = mapped_column(JSON, comment="飞书卡片发送快照，包含模板 ID、固定版本及变量值")
    __table_args__ = (UniqueConstraint("batch_id", "employee_id"), Index("ix_ledger_employee_month", "employee_id", "month"), {"comment": "逐人积分流水，同一批次每名员工只记账一次"})


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, comment="消息投递记录 ID（UUID）")
    ledger_id: Mapped[str] = mapped_column(ForeignKey("ledger.id"), index=True, comment="关联积分流水 ID，同一流水对同一接收人只投递一次")
    recipient_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), comment="通知接收人的系统内部员工 ID")
    recipient_open_id: Mapped[str] = mapped_column(String(100), comment="接收人飞书 open_id 快照，用于私聊发送")
    recipient_name: Mapped[str] = mapped_column(String(200), comment="接收人姓名快照")
    uuid: Mapped[str] = mapped_column(String(36), unique=True, default=new_id, comment="飞书消息去重 UUID，重试时保持不变")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, comment="投递状态：pending 待发送，sending 发送中，sent 成功，failed 明确失败，review 待核实")
    attempts: Mapped[int] = mapped_column(Integer, default=0, comment="当前重试周期的尝试次数，人工重试时重置")
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否存在发送结果不确定的尝试，用于限制重复发送")
    first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, comment="当前重试周期首次尝试时间（UTC），用于去重窗口判断")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="下次可尝试发送时间（UTC）")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, comment="worker 任务领取租约到期时间（UTC）")
    lease_token: Mapped[str | None] = mapped_column(String(36), comment="本次任务领取令牌，防止过期 worker 覆盖结果")
    message_id: Mapped[str | None] = mapped_column(String(100), comment="飞书发送成功返回的 message_id，供查询及后续撤回使用")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, comment="消息发送成功时间（UTC）")
    last_error: Mapped[str | None] = mapped_column(Text, comment="最近一次发送错误或待核实原因")
    __table_args__ = (UniqueConstraint("ledger_id", "recipient_id"), {"comment": "飞书卡片投递任务、重试状态及消息回执"})


class LedgerCancellation(Base):
    __tablename__ = "ledger_cancellations"
    __table_args__ = {"comment": "积分流水作废审计，每笔记分至多作废一次，原流水和卡片快照保留"}
    ledger_id: Mapped[str] = mapped_column(ForeignKey("ledger.id"), primary_key=True, comment="作废的积分流水 ID，唯一主键防止重复作废")
    actor_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), comment="申请作废的操作员 ID；历史撤回修正沿用原撤回申请人")
    cancelled_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="积分作废时间（UTC）")
    before_balance: Mapped[int] = mapped_column(Integer, comment="作废前该员工该月的实际余额")
    after_balance: Mapped[int] = mapped_column(Integer, comment="作废后按其余有效流水重算的月度余额")
    source: Mapped[str] = mapped_column(String(20), default="recall", comment="作废来源：recall 撤回操作，legacy_recall 历史已撤回消息修正")


class MessageRecall(Base):
    __tablename__ = "message_recalls"
    __table_args__ = {"comment": "飞书消息撤回任务与结果，每条投递记录至多一个任务"}
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id"), primary_key=True, comment="被撤回的投递记录 ID，关联 deliveries.id，同时作为任务主键")
    actor_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), comment="首次申请撤回的操作员 ID")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, comment="撤回状态：pending 待撤回，recalling 撤回中，recalled 已撤回，failed 失败，review 待核实")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="首次申请撤回时间（UTC）")
    attempts: Mapped[int] = mapped_column(Integer, default=0, comment="当前撤回重试周期的尝试次数")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="下次可尝试撤回时间（UTC）")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, comment="worker 撤回任务领取租约到期时间（UTC）")
    lease_token: Mapped[str | None] = mapped_column(String(36), comment="撤回任务领取令牌，防止过期 worker 覆盖结果")
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False, comment="撤回是否存在结果不确定的尝试")
    recalled_at: Mapped[datetime | None] = mapped_column(DateTime, comment="确认消息已撤回或已删除的时间（UTC）")
    last_error: Mapped[str | None] = mapped_column(Text, comment="最近一次撤回错误或待核实原因")
    error_code: Mapped[int | None] = mapped_column(Integer, comment="最近一次飞书撤回错误码，用于判断是否允许重试")


class LoginState(Base):
    __tablename__ = "login_states"
    __table_args__ = {"comment": "飞书 OAuth 一次性登录状态与 PKCE 校验信息"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="OAuth state 的 HMAC-SHA256 摘要")
    verifier: Mapped[str] = mapped_column(String(128), comment="PKCE code_verifier，仅服务端保存，用于交换授权码")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, comment="登录状态到期时间（UTC），创建后 5 分钟")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"comment": "用户登录会话与写请求 CSRF 校验信息"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="会话令牌的 HMAC-SHA256 摘要，不保存原始 Cookie 令牌")
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, comment="登录员工 ID，关联 employees.id")
    csrf_token: Mapped[str] = mapped_column(String(100), comment="写请求使用的 CSRF 校验令牌")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, comment="会话到期时间（UTC）")


class EventReceipt(Base):
    __tablename__ = "event_receipts"
    __table_args__ = {"comment": "已处理的飞书通讯录事件去重记录"}
    id: Mapped[str] = mapped_column(String(100), primary_key=True, comment="飞书事件 event_id，用于防止重复处理")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="事件首次处理时间（UTC）")


class PermissionAudit(Base):
    __tablename__ = "permission_audit"
    __table_args__ = {"comment": "员工权限变更审计记录"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id, comment="权限变更记录 ID（UUID）")
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), comment="执行变更的管理员 ID，系统初始化授权时为空")
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), comment="被变更权限的员工 ID")
    old_role: Mapped[str] = mapped_column(String(20), comment="变更前角色：admin 管理员，operator 操作员，none 未授权")
    new_role: Mapped[str] = mapped_column(String(20), comment="变更后角色：admin 管理员，operator 操作员，none 未授权")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, comment="权限变更时间（UTC）")
