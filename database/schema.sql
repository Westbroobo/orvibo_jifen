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

-- =====================================================================
-- 增量 2026-10-10（第三段）：管理员设置人员定时同步计划
-- 已有数据库只执行本段；可重复执行，不修改已有同步配置或业务记录。
-- 默认每天北京时间 02:00 同步；下次时间由 worker 初始化并持久化。
-- 手动及飞书人员变更同步不改变定时计划，失败后等待 5 分钟重试。
-- =====================================================================
SET NAMES utf8mb4;
SET @sync_schedule_columns = CONCAT_WS(', ',
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'sync_enabled'), NULL,
        'ADD COLUMN sync_enabled BOOL NOT NULL DEFAULT 1 COMMENT ''是否开启定时全量同步，不影响手动及人员事件同步'''),
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'sync_interval_days'), NULL,
        'ADD COLUMN sync_interval_days INTEGER NOT NULL DEFAULT 1 COMMENT ''定时同步间隔天数，范围 1 至 365 天'''),
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'sync_time'), NULL,
        'ADD COLUMN sync_time VARCHAR(5) NOT NULL DEFAULT ''02:00'' COMMENT ''北京时间的定时同步时刻，格式 HH:MM'''),
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'next_sync_at'), NULL,
        'ADD COLUMN next_sync_at DATETIME NULL COMMENT ''下次定时全量同步时间（UTC），关闭定时同步时为空'''),
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'sync_retry_at'), NULL,
        'ADD COLUMN sync_retry_at DATETIME NULL COMMENT ''同步失败后允许重试的时间（UTC），手动同步可提前重试''')
);
SET @sync_schedule_sql = IF(@sync_schedule_columns = '', 'SELECT 1', CONCAT('ALTER TABLE system_state ', @sync_schedule_columns));
PREPARE sync_schedule_statement FROM @sync_schedule_sql;
EXECUTE sync_schedule_statement;
DEALLOCATE PREPARE sync_schedule_statement;

-- =====================================================================
-- 增量 2026-10-10（第四段）：同步任务心跳与异常恢复
-- 已有数据库只执行本段；尚未执行第三段时先执行第三段。
-- 可重复执行；旧任务没有有效租约，新 worker 会接管，避免长时间显示同步中。
-- =====================================================================
SET NAMES utf8mb4;
SET @sync_lease_columns = CONCAT_WS(', ',
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'sync_lease_token'), NULL,
        'ADD COLUMN sync_lease_token VARCHAR(36) NULL COMMENT ''当前组织同步任务的归属令牌，防止过期任务覆盖新状态'''),
    IF(EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'system_state' AND COLUMN_NAME = 'sync_lease_until'), NULL,
        'ADD COLUMN sync_lease_until DATETIME NULL COMMENT ''组织同步任务租约到期时间（UTC），运行期间续期，进程退出后自动失效''')
);
SET @sync_lease_sql = IF(@sync_lease_columns = '', 'SELECT 1', CONCAT('ALTER TABLE system_state ', @sync_lease_columns));
PREPARE sync_lease_statement FROM @sync_lease_sql;
EXECUTE sync_lease_statement;
DEALLOCATE PREPARE sync_lease_statement;

-- =====================================================================
-- 增量 2026-10-10（第五段）：积分系统表名统一增加 orvibo_jifen_ 前缀
-- 先停止 API 和 worker，在同一个 SQL 会话执行本段，再启动新版服务。
-- 尚未执行的前置增量先按顺序补齐；空数据库执行全文，最后自动改名。
-- 仅处理以下 16 张积分系统表，保留原数据、索引、中文注释及外键关系。
-- 已改名的表自动跳过；若目标名称已被其他表占用，整条改名语句失败。
-- 本段可重复执行，后续增量统一使用带前缀的表名。
-- =====================================================================
SET NAMES utf8mb4;
SET @jifen_prefix_previous_concat_length = @@SESSION.group_concat_max_len;
SET SESSION group_concat_max_len = CAST(GREATEST(@jifen_prefix_previous_concat_length, 8192) AS UNSIGNED);
SET @jifen_prefix_rename_pairs = (
    SELECT GROUP_CONCAT(
        CONCAT('`', TABLE_NAME, '` TO `orvibo_jifen_', TABLE_NAME, '`')
        ORDER BY TABLE_NAME SEPARATOR ', '
    )
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
      AND TABLE_NAME IN (
          'balances', 'batches', 'deliveries', 'departments', 'employees',
          'event_receipts', 'ledger', 'ledger_cancellations', 'login_states',
          'memberships', 'message_recalls', 'permission_audit', 'presets',
          'previews', 'sessions', 'system_state'
      )
);
SET @jifen_prefix_rename_sql = IF(
    @jifen_prefix_rename_pairs IS NULL,
    'SELECT ''没有需要增加前缀的积分系统表'' AS result',
    CONCAT('RENAME TABLE ', @jifen_prefix_rename_pairs)
);
SET SESSION group_concat_max_len = @jifen_prefix_previous_concat_length;
PREPARE jifen_prefix_rename_statement FROM @jifen_prefix_rename_sql;
EXECUTE jifen_prefix_rename_statement;
DEALLOCATE PREPARE jifen_prefix_rename_statement;

-- =====================================================================
-- 增量 2026-10-12（第六段）：移除全部积分系统外键并补充查询索引
-- 先停止 API/worker，确认第五段已完成，在同一个 SQL 会话执行整个本段。
-- 仅修改 16 张积分系统表；不删除数据，不移除主键、唯一索引或现有索引。
-- 关联完整性改由新版代码在事务内校验；人员和业务历史禁止物理删除。
-- 根据当前实际外键名称逐个删除，兼容改名前后名称及错误引用旧表的外键。
-- 可重复执行；已有同等左前缀索引时跳过，避免重复创建。
-- 需 ALTER 和 CREATE ROUTINE 权限；临时过程执行后删除，不常驻数据库。
-- =====================================================================
SET NAMES utf8mb4;
DROP PROCEDURE IF EXISTS orvibo_jifen_remove_foreign_keys;
DELIMITER $$
CREATE PROCEDURE orvibo_jifen_remove_foreign_keys()
BEGIN
    DECLARE finished BOOL DEFAULT FALSE;
    DECLARE target_table VARCHAR(100);
    DECLARE target_constraint VARCHAR(100);
    DECLARE target_index VARCHAR(100);
    DECLARE target_columns VARCHAR(200);
    DECLARE index_comment VARCHAR(200);
    DECLARE covered_indexes INT;
    DECLARE foreign_keys CURSOR FOR
        SELECT TABLE_NAME, CONSTRAINT_NAME
        FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME IN (
              'orvibo_jifen_balances', 'orvibo_jifen_batches', 'orvibo_jifen_deliveries',
              'orvibo_jifen_departments', 'orvibo_jifen_employees', 'orvibo_jifen_event_receipts',
              'orvibo_jifen_ledger', 'orvibo_jifen_ledger_cancellations', 'orvibo_jifen_login_states',
              'orvibo_jifen_memberships', 'orvibo_jifen_message_recalls', 'orvibo_jifen_permission_audit',
              'orvibo_jifen_presets', 'orvibo_jifen_previews', 'orvibo_jifen_sessions', 'orvibo_jifen_system_state'
          )
        ORDER BY TABLE_NAME, CONSTRAINT_NAME;
    DECLARE required_indexes CURSOR FOR
        SELECT 'orvibo_jifen_memberships', 'ix_memberships_department', 'department_id', '按部门查询员工归属'
        UNION ALL SELECT 'orvibo_jifen_balances', 'ix_balances_month', 'month', '获取当月所有员工积分，避免扫描历史月份'
        UNION ALL SELECT 'orvibo_jifen_employees', 'ix_employees_role_status', 'role,status', '检查有效管理员数量'
        UNION ALL SELECT 'orvibo_jifen_batches', 'ix_batches_operator_created', 'operator_id,created_at', '查询操作员发送记录并按时间排序'
        UNION ALL SELECT 'orvibo_jifen_deliveries', 'ix_deliveries_status_next', 'status,next_attempt_at', '领取待发送消息任务'
        UNION ALL SELECT 'orvibo_jifen_deliveries', 'ix_deliveries_status_lease', 'status,lease_until', '恢复租约过期的发送任务'
        UNION ALL SELECT 'orvibo_jifen_message_recalls', 'ix_message_recalls_status_next', 'status,next_attempt_at', '领取待撤回消息任务'
        UNION ALL SELECT 'orvibo_jifen_message_recalls', 'ix_message_recalls_status_lease', 'status,lease_until', '恢复租约过期的撤回任务'
        UNION ALL SELECT 'orvibo_jifen_message_recalls', 'ix_message_recalls_status_requested', 'status,requested_at', '按申请顺序补处理已撤回积分';
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET finished = TRUE;

    IF (SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN (
            'orvibo_jifen_balances', 'orvibo_jifen_batches', 'orvibo_jifen_deliveries',
            'orvibo_jifen_departments', 'orvibo_jifen_employees', 'orvibo_jifen_event_receipts',
            'orvibo_jifen_ledger', 'orvibo_jifen_ledger_cancellations', 'orvibo_jifen_login_states',
            'orvibo_jifen_memberships', 'orvibo_jifen_message_recalls', 'orvibo_jifen_permission_audit',
            'orvibo_jifen_presets', 'orvibo_jifen_previews', 'orvibo_jifen_sessions', 'orvibo_jifen_system_state'
        )) <> 16 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '缺少积分系统表，请先按顺序执行第五段及前置增量';
    END IF;

    OPEN foreign_keys;
    remove_loop: LOOP
        FETCH foreign_keys INTO target_table, target_constraint;
        IF finished THEN LEAVE remove_loop; END IF;
        SET @jifen_remove_fk_sql = CONCAT('ALTER TABLE `', target_table, '` DROP FOREIGN KEY `',
                                          REPLACE(target_constraint, '`', '``'), '`');
        PREPARE jifen_remove_fk_statement FROM @jifen_remove_fk_sql;
        EXECUTE jifen_remove_fk_statement;
        DEALLOCATE PREPARE jifen_remove_fk_statement;
    END LOOP;
    CLOSE foreign_keys;

    SET finished = FALSE;
    OPEN required_indexes;
    index_loop: LOOP
        FETCH required_indexes INTO target_table, target_index, target_columns, index_comment;
        IF finished THEN LEAVE index_loop; END IF;
        SELECT COUNT(*) INTO covered_indexes FROM (
            SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') AS indexed_columns,
                   MAX(SUB_PART IS NOT NULL) AS shortened, MIN(IS_VISIBLE = 'YES') AS visible
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = target_table
            GROUP BY INDEX_NAME
        ) AS existing_indexes
        WHERE shortened = 0 AND visible = 1
          AND (indexed_columns = target_columns OR indexed_columns LIKE CONCAT(target_columns, ',%'));
        IF covered_indexes = 0 THEN
            SET @jifen_add_index_sql = CONCAT('ALTER TABLE `', target_table, '` ADD INDEX `', target_index,
                '` (`', REPLACE(target_columns, ',', '`, `'), '`) COMMENT ', QUOTE(index_comment));
            PREPARE jifen_add_index_statement FROM @jifen_add_index_sql;
            EXECUTE jifen_add_index_statement;
            DEALLOCATE PREPARE jifen_add_index_statement;
        END IF;
    END LOOP;
    CLOSE required_indexes;
END$$
DELIMITER ;
CALL orvibo_jifen_remove_foreign_keys();
DROP PROCEDURE orvibo_jifen_remove_foreign_keys;

-- 执行结果应为 0；历史建表段仅保留升级路径，最终结构不含外键。
SELECT COUNT(*) AS `积分系统剩余外键数量`
FROM information_schema.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = DATABASE() AND LEFT(TABLE_NAME, 13) = 'orvibo_jifen_';

-- =====================================================================
-- 增量 2026-10-12（第七段）：公共及个人发送名单
-- 先停止 API/worker，确认第六段已执行，在同一 SQL 会话执行整个本段。
-- 原名单全部保留为个人名单，原部门交集规则不变；新建名单使用部门并集。
-- 不增加外键；公共名称由应用事务锁校验，个人名称由唯一索引校验。
-- 可重复执行；需要 ALTER 和 CREATE ROUTINE 权限，执行后删除临时过程。
-- =====================================================================
SET NAMES utf8mb4;
DROP PROCEDURE IF EXISTS orvibo_jifen_upgrade_presets;
DELIMITER $$
CREATE PROCEDURE orvibo_jifen_upgrade_presets()
BEGIN
    DECLARE finished BOOL DEFAULT FALSE;
    DECLARE old_index VARCHAR(100);
    DECLARE old_unique_indexes CURSOR FOR
        SELECT INDEX_NAME FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orvibo_jifen_presets'
          AND NON_UNIQUE = 0 AND INDEX_NAME <> 'PRIMARY'
        GROUP BY INDEX_NAME
        HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') = 'owner_id,name';
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET finished = TRUE;

    IF NOT EXISTS (SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orvibo_jifen_presets') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '缺少积分系统名单表，请先执行前置增量';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orvibo_jifen_presets' AND COLUMN_NAME = 'scope') THEN
        ALTER TABLE orvibo_jifen_presets ADD COLUMN scope VARCHAR(20) NOT NULL DEFAULT 'personal'
            COMMENT '名单可见范围：personal 个人，public 公共（管理员维护）' AFTER owner_id;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orvibo_jifen_presets' AND INDEX_NAME = 'uq_presets_owner_scope_name') THEN
        ALTER TABLE orvibo_jifen_presets ADD UNIQUE INDEX uq_presets_owner_scope_name (owner_id, scope, name)
            COMMENT '同一创建人及可见范围内名单名称唯一';
    END IF;
    OPEN old_unique_indexes;
    remove_loop: LOOP
        FETCH old_unique_indexes INTO old_index;
        IF finished THEN LEAVE remove_loop; END IF;
        SET @jifen_presets_sql = CONCAT('ALTER TABLE orvibo_jifen_presets DROP INDEX `', REPLACE(old_index, '`', '``'), '`');
        PREPARE jifen_presets_statement FROM @jifen_presets_sql;
        EXECUTE jifen_presets_statement;
        DEALLOCATE PREPARE jifen_presets_statement;
    END LOOP;
    CLOSE old_unique_indexes;
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orvibo_jifen_presets' AND INDEX_NAME = 'ix_presets_scope_name') THEN
        ALTER TABLE orvibo_jifen_presets ADD INDEX ix_presets_scope_name (scope, name)
            COMMENT '查询公共名单及校验同名名单';
    END IF;
    ALTER TABLE orvibo_jifen_presets
        COMMENT = '公共及个人发送名单，使用时按最新人员目录解析',
        MODIFY id VARCHAR(36) NOT NULL COMMENT '发送名单 ID（UUID）',
        MODIFY owner_id VARCHAR(36) NOT NULL COMMENT '名单创建人 ID；个人名单仅本人可访问',
        MODIFY name VARCHAR(100) NOT NULL COMMENT '名单名称，公共名单全局唯一，个人名单在本人名下唯一',
        MODIFY selection JSON NOT NULL COMMENT '通知范围条件：匹配方式、部门 ID、部门层级及指定人员';
END$$
DELIMITER ;
CALL orvibo_jifen_upgrade_presets();
DROP PROCEDURE orvibo_jifen_upgrade_presets;
