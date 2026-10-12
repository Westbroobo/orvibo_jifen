import os
from datetime import datetime

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-32-characters")
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import AppSession, Base, make_engine
from app.models import Department, Employee, Membership, SystemState


@pytest.fixture(scope="session")
def test_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("请用 database/schema.sql 初始化独立 MySQL 测试库，再设置 TEST_DATABASE_URL")
    from sqlalchemy.engine import make_url
    address = make_url(url)
    if address.get_backend_name() != "mysql" or not (address.database or "").startswith("jifen_test_"):
        raise RuntimeError("测试只能连接 jifen_test_ 前缀的独立 MySQL 数据库")
    engine = make_engine(url)
    missing = set(Base.metadata.tables) - set(inspect(engine).get_table_names())
    if missing:
        engine.dispose()
        raise RuntimeError("测试库缺少表，请手动执行 database/schema.sql：" + "、".join(sorted(missing)))
    if any(inspect(engine).get_foreign_keys(name) for name in Base.metadata.tables):
        engine.dispose()
        raise RuntimeError("测试库仍有外键，请先执行 database/schema.sql 第六段增量")
    yield engine
    engine.dispose()


@pytest.fixture
def factory(test_engine):
    factory = sessionmaker(test_engine, class_=AppSession, expire_on_commit=False)
    # 测试库清理走独立连接；业务会话禁止物理删除人员和历史。
    with test_engine.begin() as connection:
        for table in Base.metadata.tables.values():
            connection.execute(delete(table))
    with factory.begin() as db:
        db.add(SystemState(id=1))
        db.add_all([
            Department(id="rd", name="研发", path_ids=["rd"], path_names=["研发"]),
            Department(id="sw", name="软件", parent_id="rd", path_ids=["rd", "sw"], path_names=["研发", "软件"]),
            Department(id="team", name="平台", parent_id="sw", path_ids=["rd", "sw", "team"], path_names=["研发", "软件", "平台"]),
            Department(id="sales", name="销售", path_ids=["sales"], path_names=["销售"]),
            Department(id="east", name="华东", parent_id="sales", path_ids=["sales", "east"], path_names=["销售", "华东"]),
        ])
        db.add_all([
            Employee(id="admin", open_id="ou_admin", name="管理员", status="active", role="admin"),
            Employee(id="operator", open_id="ou_operator", name="操作员", status="active", role="operator"),
            Employee(id="a", open_id="ou_a", name="张三", status="active"),
            Employee(id="b", open_id="ou_b", name="李四", status="active"),
            Employee(id="c", open_id="ou_c", name="多部门员工", status="active"),
            Employee(id="gone", open_id="ou_gone", name="离职人员", status="resigned"),
        ])
        db.flush()
        db.add_all([Membership(employee_id="a", department_id="team"), Membership(employee_id="b", department_id="east"),
                    Membership(employee_id="c", department_id="team"), Membership(employee_id="c", department_id="east")])
    return factory


@pytest.fixture
def settings():
    return Settings(_env_file=None, app_env="development", database_url="sqlite://")


@pytest.fixture
def when():
    return datetime(2026, 10, 6, 6, 0)
