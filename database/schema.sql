-- ORVIBO_员工积分系统：MySQL 8 数据库结构的唯一维护脚本。
-- 执行前，先选中 DATABASE_URL 指定的数据库；数据库字符集使用 utf8mb4。
-- 新数据库：在空数据库中执行全文，包含建表、初始化数据及末尾增量。
-- 已有数据库：只执行末尾尚未应用的增量段，不重复执行基础建表部分。
-- 后续结构变更按日期追加在本文件末尾，由管理员手动执行；启动程序不建表、不升级结构。
-- 所有表和字段均含中文注释。

SET NAMES utf8mb4;

-- 基础建表

CREATE TABLE departments (
    id VARCHAR(100) NOT NULL COMMENT '飞书部门 open_department_id',
    name VARCHAR(200) NOT NULL COMMENT '部门名称',
    parent_id VARCHAR(100) NOT NULL COMMENT '上级部门 open_department_id，0 表示根节点',
    path_ids JSON NOT NULL COMMENT '从一级部门到当前部门的完整部门 ID 数组',
    path_names JSON NOT NULL COMMENT '从一级部门到当前部门的完整部门名称数组',
    active BOOL NOT NULL COMMENT '部门是否在最近一次完整同步范围内有效',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='飞书部门目录及完整层级路径';

CREATE TABLE employees (
    id VARCHAR(36) NOT NULL COMMENT '系统内部员工 ID（UUID）',
    open_id VARCHAR(100) NOT NULL COMMENT '员工在当前飞书应用中的 open_id，用于登录及消息发送',
    name VARCHAR(200) NOT NULL COMMENT '员工姓名',
    avatar_url TEXT NOT NULL COMMENT '员工头像地址',
    status VARCHAR(20) NOT NULL COMMENT '人员状态：active 在职可用，resigned 离职，inactive 冻结或退出，unknown 待核实',
    `role` VARCHAR(20) NOT NULL COMMENT '系统角色：admin 管理员，operator 操作员，none 未授权',
    feishu_status JSON NOT NULL COMMENT '飞书通讯录返回的原始人员状态',
    updated_at DATETIME NOT NULL COMMENT '人员信息最近更新时间（UTC）',
    PRIMARY KEY (id), 
    UNIQUE (open_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='员工基本信息、飞书身份与操作权限';

CREATE TABLE event_receipts (
    id VARCHAR(100) NOT NULL COMMENT '飞书事件 event_id，用于防止重复处理',
    received_at DATETIME NOT NULL COMMENT '事件首次处理时间（UTC）',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='已处理的飞书通讯录事件去重记录';

CREATE TABLE login_states (
    id VARCHAR(64) NOT NULL COMMENT 'OAuth state 的 HMAC-SHA256 摘要',
    verifier VARCHAR(128) NOT NULL COMMENT 'PKCE code_verifier，仅服务端保存，用于交换授权码',
    expires_at DATETIME NOT NULL COMMENT '登录状态到期时间（UTC），创建后 5 分钟',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='飞书 OAuth 一次性登录状态与 PKCE 校验信息';

CREATE INDEX ix_login_states_expires_at ON login_states (expires_at);

CREATE TABLE system_state (
    id INTEGER NOT NULL AUTO_INCREMENT COMMENT '状态记录主键，固定为 1',
    directory_version INTEGER NOT NULL COMMENT '组织架构版本号，用于同步并发校验',
    last_sync_at DATETIME COMMENT '最近一次成功同步时间（UTC）',
    last_sync_error TEXT COMMENT '最近一次组织同步错误，成功后清空',
    sync_requested BOOL NOT NULL COMMENT '是否待执行全量组织同步',
    sync_started_at DATETIME COMMENT '当前同步任务开始时间（UTC），用于防止重复执行',
    bootstrap_done BOOL NOT NULL COMMENT '是否已完成初始管理员权限初始化',
    events_connected_at DATETIME COMMENT '飞书事件长连接最近重连成功时间（UTC），断开时清空',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统运行状态与组织同步控制（固定单行）';

CREATE TABLE balances (
    employee_id VARCHAR(36) NOT NULL COMMENT '记分员工 ID，关联 employees.id',
    month VARCHAR(7) NOT NULL COMMENT '北京时间自然月，格式 YYYY-MM',
    total INTEGER NOT NULL COMMENT '本月当前最终总分，无记录时以 60 分为起点',
    version INTEGER NOT NULL COMMENT '余额版本号，每次记账递增，用于预览并发校验',
    PRIMARY KEY (employee_id, month), 
    FOREIGN KEY(employee_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='员工月度积分余额，每人每月唯一';

CREATE TABLE batches (
    id VARCHAR(36) NOT NULL COMMENT '积分操作批次 ID（UUID）',
    operator_id VARCHAR(36) NOT NULL COMMENT '执行本次操作的员工 ID',
    idempotency_key VARCHAR(100) NOT NULL COMMENT '客户端提交幂等键，同一操作员下唯一，防止重复记账',
    preview_id VARCHAR(64) NOT NULL COMMENT '所用预览凭据摘要，确保一个预览只记账一次',
    month VARCHAR(7) NOT NULL COMMENT '北京时间记分自然月，格式 YYYY-MM',
    delta INTEGER NOT NULL COMMENT '本次积分变动值，正数加分，负数扣分，不能为 0',
    reason TEXT NOT NULL COMMENT '加分或扣分原因，同批次所有记分对象共用',
    snapshot JSON NOT NULL COMMENT '确认时的完整预览快照，保留人员、总分、卡片及通知名单',
    created_at DATETIME NOT NULL COMMENT '批次记账时间（UTC）',
    PRIMARY KEY (id), 
    FOREIGN KEY(operator_id) REFERENCES employees (id), 
    UNIQUE (operator_id, idempotency_key), 
    UNIQUE (preview_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='已确认的积分操作批次与幂等记录';

CREATE INDEX ix_batches_created_at ON batches (created_at);

CREATE INDEX ix_batches_operator_id ON batches (operator_id);

CREATE TABLE memberships (
    employee_id VARCHAR(36) NOT NULL COMMENT '系统内部员工 ID，关联 employees.id',
    department_id VARCHAR(100) NOT NULL COMMENT '所属部门 ID，关联 departments.id',
    PRIMARY KEY (employee_id, department_id), 
    FOREIGN KEY(department_id) REFERENCES departments (id), 
    FOREIGN KEY(employee_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='员工与部门的多对多归属关系';

CREATE TABLE permission_audit (
    id VARCHAR(36) NOT NULL COMMENT '权限变更记录 ID（UUID）',
    actor_id VARCHAR(36) COMMENT '执行变更的管理员 ID，系统初始化授权时为空',
    employee_id VARCHAR(36) NOT NULL COMMENT '被变更权限的员工 ID',
    old_role VARCHAR(20) NOT NULL COMMENT '变更前角色：admin 管理员，operator 操作员，none 未授权',
    new_role VARCHAR(20) NOT NULL COMMENT '变更后角色：admin 管理员，operator 操作员，none 未授权',
    created_at DATETIME NOT NULL COMMENT '权限变更时间（UTC）',
    PRIMARY KEY (id), 
    FOREIGN KEY(actor_id) REFERENCES employees (id), 
    FOREIGN KEY(employee_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='员工权限变更审计记录';

CREATE TABLE presets (
    id VARCHAR(36) NOT NULL COMMENT '个人发送配置 ID（UUID）',
    owner_id VARCHAR(36) NOT NULL COMMENT '配置所属员工 ID，仅本人可访问',
    name VARCHAR(100) NOT NULL COMMENT '配置名称，同一用户下不可重复',
    selection JSON NOT NULL COMMENT '通知范围条件：部门层级、选择模式、勾选人员及额外人员',
    updated_at DATETIME NOT NULL COMMENT '配置最近更新时间（UTC）',
    PRIMARY KEY (id), 
    FOREIGN KEY(owner_id) REFERENCES employees (id), 
    UNIQUE (owner_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户私有的通知范围配置';

CREATE INDEX ix_presets_owner_id ON presets (owner_id);

CREATE TABLE previews (
    id VARCHAR(64) NOT NULL COMMENT '预览凭据的 SHA-256 摘要，不保存原始凭据',
    owner_id VARCHAR(36) NOT NULL COMMENT '创建预览的操作员 ID',
    request JSON NOT NULL COMMENT '预览请求：记分对象、分值、原因、覆盖总分及通知范围',
    snapshot JSON NOT NULL COMMENT '预览计算结果快照，含逐人总分、余额版本、卡片及通知名单',
    created_at DATETIME NOT NULL COMMENT '预览创建时间（UTC）',
    expires_at DATETIME NOT NULL COMMENT '预览到期时间（UTC），创建后 10 分钟',
    batch_id VARCHAR(36) COMMENT '确认后关联的记账批次 ID，未确认时为空',
    PRIMARY KEY (id), 
    FOREIGN KEY(owner_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='积分操作预览凭据与内容快照';

CREATE INDEX ix_previews_expires_at ON previews (expires_at);

CREATE TABLE sessions (
    id VARCHAR(64) NOT NULL COMMENT '会话令牌的 HMAC-SHA256 摘要，不保存原始 Cookie 令牌',
    employee_id VARCHAR(36) NOT NULL COMMENT '登录员工 ID，关联 employees.id',
    csrf_token VARCHAR(100) NOT NULL COMMENT '写请求使用的 CSRF 校验令牌',
    expires_at DATETIME NOT NULL COMMENT '会话到期时间（UTC）',
    PRIMARY KEY (id), 
    FOREIGN KEY(employee_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户登录会话与写请求 CSRF 校验信息';

CREATE INDEX ix_sessions_employee_id ON sessions (employee_id);

CREATE INDEX ix_sessions_expires_at ON sessions (expires_at);

CREATE TABLE ledger (
    id VARCHAR(36) NOT NULL COMMENT '积分流水 ID（UUID）',
    batch_id VARCHAR(36) NOT NULL COMMENT '所属操作批次 ID，关联 batches.id',
    employee_id VARCHAR(36) NOT NULL COMMENT '本条流水的记分员工 ID',
    month VARCHAR(7) NOT NULL COMMENT '北京时间记分自然月，格式 YYYY-MM',
    delta INTEGER NOT NULL COMMENT '本次积分变动值，正数加分，负数扣分',
    before_total INTEGER NOT NULL COMMENT '操作前本月总分，月内首次记账为 60 分',
    final_total INTEGER NOT NULL COMMENT '本次操作后的最终总分，作为后续记账起点',
    override_total INTEGER COMMENT '用户手动覆盖的最终总分，空表示自动计算，0 为有效值',
    card JSON NOT NULL COMMENT '飞书卡片发送快照，包含模板 ID、固定版本及变量值',
    PRIMARY KEY (id), 
    FOREIGN KEY(batch_id) REFERENCES batches (id), 
    FOREIGN KEY(employee_id) REFERENCES employees (id), 
    UNIQUE (batch_id, employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='逐人积分流水，同一批次每名员工只记账一次';

CREATE INDEX ix_ledger_batch_id ON ledger (batch_id);

CREATE INDEX ix_ledger_employee_month ON ledger (employee_id, month);

CREATE TABLE deliveries (
    id VARCHAR(36) NOT NULL COMMENT '消息投递记录 ID（UUID）',
    ledger_id VARCHAR(36) NOT NULL COMMENT '关联积分流水 ID，同一流水对同一接收人只投递一次',
    recipient_id VARCHAR(36) NOT NULL COMMENT '通知接收人的系统内部员工 ID',
    recipient_open_id VARCHAR(100) NOT NULL COMMENT '接收人飞书 open_id 快照，用于私聊发送',
    recipient_name VARCHAR(200) NOT NULL COMMENT '接收人姓名快照',
    uuid VARCHAR(36) NOT NULL COMMENT '飞书消息去重 UUID，重试时保持不变',
    status VARCHAR(20) NOT NULL COMMENT '投递状态：pending 待发送，sending 发送中，sent 成功，failed 明确失败，review 待核实',
    attempts INTEGER NOT NULL COMMENT '当前重试周期的尝试次数，人工重试时重置',
    uncertain BOOL NOT NULL COMMENT '是否存在发送结果不确定的尝试，用于限制重复发送',
    first_attempt_at DATETIME COMMENT '当前重试周期首次尝试时间（UTC），用于去重窗口判断',
    next_attempt_at DATETIME NOT NULL COMMENT '下次可尝试发送时间（UTC）',
    lease_until DATETIME COMMENT 'worker 任务领取租约到期时间（UTC）',
    lease_token VARCHAR(36) COMMENT '本次任务领取令牌，防止过期 worker 覆盖结果',
    message_id VARCHAR(100) COMMENT '飞书发送成功返回的 message_id，供查询及后续撤回使用',
    sent_at DATETIME COMMENT '消息发送成功时间（UTC）',
    last_error TEXT COMMENT '最近一次发送错误或待核实原因',
    PRIMARY KEY (id), 
    FOREIGN KEY(ledger_id) REFERENCES ledger (id), 
    FOREIGN KEY(recipient_id) REFERENCES employees (id), 
    UNIQUE (ledger_id, recipient_id), 
    UNIQUE (uuid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='飞书卡片投递任务、重试状态及消息回执';

CREATE INDEX ix_deliveries_ledger_id ON deliveries (ledger_id);

CREATE INDEX ix_deliveries_status ON deliveries (status);

INSERT INTO system_state (id, directory_version, sync_requested, bootstrap_done) VALUES (1, 0, true, false);

-- 增量 2026-10-09：员工企业 user_id（已存在该字段的数据库跳过本段）

ALTER TABLE employees ADD COLUMN user_id VARCHAR(100) COMMENT '飞书企业内 user_id，用于匹配初始管理员';

ALTER TABLE employees ADD CONSTRAINT uq_employees_user_id UNIQUE (user_id);

-- =====================================================================
-- 增量 2026-10-10：消息撤回（已有数据库只执行本段至文件末尾，可重复执行）
-- 保留员工、积分、投递数据；撤回任务与积分记账独立保存。
-- 外键字段沿用原表的类型、字符集和排序规则，避免 MySQL 3780 错误。
-- 请在同一个 SQL 会话中执行整个增量段；需要建表及外键引用权限。
-- =====================================================================
SET NAMES utf8mb4;

SET @recall_delivery_id_definition = (
    SELECT CONCAT(COLUMN_TYPE, ' CHARACTER SET ', CHARACTER_SET_NAME, ' COLLATE ', COLLATION_NAME)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'deliveries' AND COLUMN_NAME = 'id'
);
SET @recall_actor_id_definition = (
    SELECT CONCAT(COLUMN_TYPE, ' CHARACTER SET ', CHARACTER_SET_NAME, ' COLLATE ', COLLATION_NAME)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'employees' AND COLUMN_NAME = 'id'
);

SET @recall_create_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS message_recalls (
    delivery_id ', @recall_delivery_id_definition, ' NOT NULL COMMENT ''被撤回的投递记录 ID，关联 deliveries.id，同时作为任务主键'',
    actor_id ', @recall_actor_id_definition, ' NOT NULL COMMENT ''首次申请撤回的操作员 ID'',
    status VARCHAR(20) NOT NULL COMMENT ''撤回状态：pending 待撤回，recalling 撤回中，recalled 已撤回，failed 失败，review 待核实'',
    requested_at DATETIME NOT NULL COMMENT ''首次申请撤回时间（UTC）'',
    attempts INTEGER NOT NULL COMMENT ''当前撤回重试周期的尝试次数'',
    next_attempt_at DATETIME NOT NULL COMMENT ''下次可尝试撤回时间（UTC）'',
    lease_until DATETIME COMMENT ''worker 撤回任务领取租约到期时间（UTC）'',
    lease_token VARCHAR(36) COMMENT ''撤回任务领取令牌，防止过期 worker 覆盖结果'',
    uncertain BOOL NOT NULL COMMENT ''撤回是否存在结果不确定的尝试'',
    recalled_at DATETIME COMMENT ''确认消息已撤回或已删除的时间（UTC）'',
    last_error TEXT COMMENT ''最近一次撤回错误或待核实原因'',
    error_code INTEGER COMMENT ''最近一次飞书撤回错误码，用于判断是否允许重试'',
    PRIMARY KEY (delivery_id),
    KEY ix_message_recalls_status (status),
    FOREIGN KEY (delivery_id) REFERENCES deliveries (id),
    FOREIGN KEY (actor_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT=''飞书消息撤回任务与结果，每条投递记录至多一个任务'''
);

PREPARE recall_create_statement FROM @recall_create_sql;
EXECUTE recall_create_statement;
DEALLOCATE PREPARE recall_create_statement;

-- =====================================================================
-- 增量 2026-10-10（第二段）：撤回对应记分作废
-- 已有数据库只执行本段；首次执行需先完成上面的消息撤回增量。
-- 可重复执行，只增加作废审计表，不删除员工、积分或消息记录。
-- 只有同一笔记分的全部通知撤回成功才作废，部分撤回仍保留积分。
-- 作废时重算该月余额；历史全部通知已撤回的记分由 worker 补记作废。
-- =====================================================================
SET NAMES utf8mb4;
SET @cancellation_ledger_id_definition = (
    SELECT CONCAT(COLUMN_TYPE, ' CHARACTER SET ', CHARACTER_SET_NAME, ' COLLATE ', COLLATION_NAME)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ledger' AND COLUMN_NAME = 'id'
);
SET @cancellation_actor_id_definition = (
    SELECT CONCAT(COLUMN_TYPE, ' CHARACTER SET ', CHARACTER_SET_NAME, ' COLLATE ', COLLATION_NAME)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'employees' AND COLUMN_NAME = 'id'
);
SET @cancellation_create_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS ledger_cancellations (
    ledger_id ', @cancellation_ledger_id_definition, ' NOT NULL COMMENT ''作废的积分流水 ID，唯一主键防止重复作废'',
    actor_id ', @cancellation_actor_id_definition, ' NOT NULL COMMENT ''申请作废的操作员 ID；历史撤回修正沿用原撤回申请人'',
    cancelled_at DATETIME NOT NULL COMMENT ''积分作废时间（UTC）'',
    before_balance INTEGER NOT NULL COMMENT ''作废前该员工该月的实际余额'',
    after_balance INTEGER NOT NULL COMMENT ''作废后按其余有效流水重算的月度余额'',
    source VARCHAR(20) NOT NULL COMMENT ''作废来源：recall 撤回操作，legacy_recall 历史已撤回消息修正'',
    PRIMARY KEY (ledger_id),
    FOREIGN KEY (ledger_id) REFERENCES ledger (id),
    FOREIGN KEY (actor_id) REFERENCES employees (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT=''积分流水作废审计，每笔记分至多作废一次，原流水和卡片快照保留'''
);
PREPARE cancellation_create_statement FROM @cancellation_create_sql;
EXECUTE cancellation_create_statement;
DEALLOCATE PREPARE cancellation_create_statement;
