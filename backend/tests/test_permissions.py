"""独立 MySQL 上验证角色、数据范围、权限撤销及并发所有者保护。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import func, select

from app import auth
from app.adjustments import commit_preview, create_preview
from app.authorization import GrantRequest, delete_role, update_grant
from app.db import lock_state
from app.delivery import claim_delivery, retry_delivery
from app.models import Batch, Department, Delivery, Employee, PermissionAudit, Role, SystemState
from app.permissions import PERMISSIONS, bootstrap_owners
from app.recall import request_recall
from app.score_ledgers import query_ledgers
from test_adjustments import request, submit
from test_api import client, login
from test_recall import sent_batch


def set_grant(factory, employee="operator", **values):
    with factory.begin() as db:
        lock_state(db)
        person = db.get(Employee, employee)
        for field, value in values.items():
            setattr(person, field, value)


def owner(factory):
    set_grant(factory, "admin", role="owner")


def test_unassigned_employee_can_login_but_cannot_access_system_data(client, factory):
    with factory.begin() as db:
        from app.models import Preset
        db.add(Preset(id='old-private', owner_id='a', name='旧个人名单', scope='personal', selection={}))
        db.add(Preset(id='public-list', owner_id='admin', name='公共名单', scope='public', selection={}))
    headers = login(client, factory, "a")
    me = client.get('/api/auth/me').json()
    assert me['permissions'] == [] and not me['can_manage']
    assert me['role_name'] == '普通员工' and not me['can_access_system']
    assert me['owner_notice'] == ''
    created = client.post('/api/presets', headers=headers, json={'name': '我的名单', 'selection': {'person_ids': ['b']}})
    assert created.status_code == 403 and '数据支持组' in created.json()['detail']
    assert client.post('/api/presets', headers=headers, json={'name': '公共名单', 'scope': 'public', 'selection': {}}).status_code == 403
    assert client.put('/api/presets/old-private', headers=headers, json={'name': '修改名单', 'selection': {}}).status_code == 403
    assert client.delete('/api/presets/old-private', headers=headers).status_code == 403
    assert client.post('/api/ranges/resolve', headers=headers, json={'person_ids': ['b']}).status_code == 403
    for path in ['/api/directory', '/api/people', '/api/presets', '/api/balances', '/api/adjustments', '/api/score-ledgers', '/api/score-ledgers/export', '/api/admin/roles', '/api/admin/permission-audits']:
        assert client.get(path).status_code == 403
    assert client.post('/api/adjustments/preview', headers=headers, json=request().model_dump()).status_code == 403
    assert client.post('/api/auth/logout', headers=headers).status_code == 200


@pytest.mark.parametrize('role,permissions,allowed', [
    ('custom', [], False), ('missing', [], False), ('custom', ['history.others'], False),
    ('custom', ['ledgers.read'], True), ('custom', ['history.read'], True),
    ('custom', ['adjustments.write'], True), ('operator', [], False),
    ('admin', [], True), ('owner', [], True),
])
def test_system_access_uses_effective_permissions_and_management_identity(client, factory, test_engine, role, permissions, allowed):
    with factory.begin() as db:
        if role == 'custom':
            db.add(Role(id='custom', name='自定义角色', permissions=permissions))
        elif role != 'missing':
            db.get(Role, role).permissions = permissions
        if role != 'missing':
            db.get(Employee, 'a').role = role
    if role == 'missing':
        # 模拟已有数据引用失效角色；正常业务授权会在应用关联校验时拒绝。
        with test_engine.begin() as connection:
            connection.execute(Employee.__table__.update().where(Employee.id == 'a').values(role=role))
    headers = login(client, factory, 'a')
    assert client.get('/api/auth/me').json()['can_access_system'] is allowed
    status = 200 if allowed else 403
    for path in ['/api/directory', '/api/people', '/api/presets']:
        assert client.get(path).status_code == status
    assert client.post('/api/ranges/resolve', headers=headers, json={'person_ids': ['b']}).status_code == status


def test_existing_session_loses_list_access_and_recovers_after_reauthorization(client, factory):
    headers = login(client, factory, 'operator')
    body = {'name': '我的名单', 'selection': {'person_ids': ['a']}}
    preset_id = client.post('/api/presets', headers=headers, json=body).json()['id']
    with factory.begin() as db:
        db.get(Role, 'operator').permissions = []
    assert not client.get('/api/auth/me').json()['can_access_system']
    for path in ['/api/directory', '/api/people', '/api/presets']:
        assert client.get(path).status_code == 403
    assert client.put('/api/presets/' + preset_id, headers=headers, json=body).status_code == 403
    assert client.delete('/api/presets/' + preset_id, headers=headers).status_code == 403
    with factory.begin() as db:
        db.get(Role, 'operator').permissions = ['ledgers.read']
    assert client.get('/api/auth/me').json()['can_access_system']
    assert client.get('/api/presets').json()[0]['id'] == preset_id
    assert client.put('/api/presets/' + preset_id, headers=headers, json=body).status_code == 200
    assert client.get('/api/balances').status_code == 403


def test_role_crud_dependencies_assignment_audits_and_fixed_identity(client, factory):
    owner(factory)
    headers = login(client, factory)
    assert client.post('/api/admin/roles', headers=headers, json={'name': '错误权限', 'permissions': ['history.recall']}).status_code == 422
    created = client.post('/api/admin/roles', headers=headers, json={'name': '明细只读', 'permissions': ['ledgers.read']})
    assert created.status_code == 201
    role_id = created.json()['id']
    assert client.put('/api/admin/people/a/authorization', headers=headers, json={'role': role_id}).status_code == 200
    assert client.delete('/api/admin/roles/' + role_id, headers=headers).status_code == 409
    assert client.put('/api/admin/roles/admin', headers=headers, json={'name': '改名', 'permissions': []}).status_code == 422
    assert client.put('/api/admin/roles/owner', headers=headers, json={'name': '系统所有者', 'permissions': []}).status_code == 403
    assert client.put('/api/admin/roles/none', headers=headers, json={'name': '普通员工', 'permissions': ['adjustments.write']}).status_code == 403
    assert client.delete('/api/admin/roles/OPERATOR', headers=headers).status_code == 409
    with factory.begin() as db:
        actor = db.get(Employee, 'admin')
        update_grant('a', GrantRequest(role='none'), actor, db)
    assert client.delete('/api/admin/roles/' + role_id, headers=headers).status_code == 200
    logs = client.get('/api/admin/permission-audits').json()
    assert logs['total'] == 4
    deletion = next(x for x in logs['items'] if x['event'] == 'role' and x['after'] is None)
    assert deletion['before']['permissions'] == ['ledgers.read']
    assert deletion['actor_name'] == '管理员' and deletion['target_name'] == '明细只读'


def test_admin_can_grant_admin_but_not_owner_or_role_configuration(client, factory):
    set_grant(factory, 'a', role='owner')
    headers = login(client, factory)
    assert client.get('/api/admin/roles').status_code == 200
    assert client.post('/api/admin/roles', headers=headers, json={'name': '测试'}).status_code == 403
    assert client.put('/api/admin/roles/operator', headers=headers, json={'name': '操作员', 'permissions': []}).status_code == 403
    assert client.put('/api/admin/people/b/authorization', headers=headers, json={'role': 'admin'}).status_code == 200
    assert client.put('/api/admin/people/b/authorization', headers=headers, json={'role': 'owner'}).status_code == 403
    assert client.put('/api/admin/people/b/authorization', headers=headers, json={'role': 'OWNER'}).status_code == 403
    assert client.put('/api/admin/people/a/authorization', headers=headers, json={'role': 'owner', 'history_scope': 'own'}).status_code == 403
    assert client.put('/api/admin/people/a/authorization', headers=headers, json={'role': 'none'}).status_code == 403
    set_grant(factory, 'admin', role='operator')
    assert client.get('/api/admin/roles').status_code == 403


def test_last_owner_and_concurrent_mutual_demotion(factory):
    owner(factory)
    with factory() as db:
        with pytest.raises(HTTPException) as error:
            update_grant('admin', GrantRequest(role='admin'), db.get(Employee, 'admin'), db)
        assert error.value.status_code == 409
    set_grant(factory, 'operator', role='owner')
    barrier = Barrier(2)

    def demote(pair):
        actor_id, target_id = pair
        with factory() as db:
            actor = db.get(Employee, actor_id)  # 模拟请求在等待事务锁前已完成身份读取。
            barrier.wait()
            try:
                update_grant(target_id, GrantRequest(role='none'), actor, db)
                return 200
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(demote, [('admin', 'operator'), ('operator', 'admin')]))
    assert sorted(results) == [200, 403]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Employee).where(Employee.role == 'owner', Employee.status == 'active')) == 1


def test_role_change_does_not_expand_scopes_and_inactive_departments_fail_closed(client, factory):
    headers = login(client, factory)
    assert client.put('/api/admin/people/a/authorization', headers=headers, json={'role': 'admin'}).status_code == 200
    detail = client.get('/api/admin/people/a/authorization').json()
    assert detail['history_scope'] == detail['ledger_scope'] == 'own'
    body = {'role': 'operator', 'ledger_scope': 'departments'}
    assert client.put('/api/admin/people/a/authorization', headers=headers, json=body).status_code == 422
    assert client.put('/api/admin/people/a/authorization', headers=headers, json=body | {'ledger_department_ids': ['missing']}).status_code == 422
    body['ledger_department_ids'] = ['rd', 'rd']
    assert client.put('/api/admin/people/a/authorization', headers=headers, json=body).status_code == 200
    with factory.begin() as db:
        db.get(Department, 'rd').active = False
    assert client.put('/api/admin/people/a/authorization', headers=headers, json=body).status_code == 200
    assert client.put('/api/admin/people/b/authorization', headers=headers, json=body).status_code == 422
    assert client.get('/api/admin/people/a/authorization').json()['ledger_department_ids'] == ['rd']
    assert next(d for d in client.get('/api/admin/roles').json()['departments'] if d['id'] == 'rd')['name'].endswith('（已停用）')


def test_readonly_scope_matches_history_snapshot_list_summary_options_and_all_export_pages(client, factory, settings, when):
    # 同批跨部门，混合多部门归属。明细范围只限制流水，发送记录仍完整。
    batch = submit(factory, settings, when, request(person_ids=['a', 'b', 'c']))
    for i in range(21):
        submit(factory, settings, when + timedelta(minutes=i + 1), request(person_ids=['c']))
    set_grant(factory, ledger_scope='departments', ledger_department_ids=['rd', 'sw'], history_scope='all')
    with factory.begin() as db:
        db.get(Role, 'operator').permissions = ['ledgers.read', 'ledgers.export', 'history.read']
        db.get(Employee, 'a').status = 'resigned'
        db.get(Department, 'team').active = False
    headers = login(client, factory, 'operator')
    result = client.get('/api/score-ledgers?month=2026-10').json()
    assert result['total'] == 23 and len(result['items']) == 20
    assert result['summary'] == {'plus_total': 115, 'minus_total': 0}
    assert {d['id'] for d in result['departments']} == {'rd', 'sw', 'team'}
    assert client.get('/api/score-ledgers?month=2026-10&department_id=sales').json()['total'] == 22  # 多部门员工按同一条授权路径可见，历史筛选仍可匹配其他归属。
    second = client.get('/api/score-ledgers?month=2026-10&page=2').json()
    assert len(second['items']) == 3 and second['summary'] == result['summary']
    exported = client.get('/api/score-ledgers/export?month=2026-10')
    rows = list(load_workbook(BytesIO(exported.content), read_only=True).active.values)
    assert len(rows) == 24 and all(row[2] != '李四' for row in rows[1:])
    full = client.get('/api/adjustments/' + batch).json()
    assert len(full['snapshot']['rows']) == 3
    assert not full['can_recall'] and not full['can_retry']
    assert client.post('/api/adjustments/preview', headers=headers, json=request().model_dump()).status_code == 403
    set_grant(factory, ledger_department_ids=[])
    hidden = client.get('/api/score-ledgers?month=2026-10').json()
    assert hidden['total'] == 0 and hidden['departments'] == [] and hidden['summary']['plus_total'] == 0


def test_visible_others_requires_separate_operate_permission_even_with_recall_and_retry(client, factory, settings, when):
    batch, (delivery_id,) = sent_batch(factory, settings, when)
    # 时钟使用真实当前时间，使 API 的 24 小时窗口有效。
    from app.db import now_utc
    with factory.begin() as db:
        db.get(Delivery, delivery_id).sent_at = now_utc()
    set_grant(factory, history_scope='all')
    headers = login(client, factory, 'operator')
    detail = client.get('/api/adjustments/' + batch).json()
    assert detail['recall_available'] == 1 and not detail['can_recall']
    assert client.post('/api/adjustments/' + batch + '/recall', headers=headers).status_code == 403
    with factory.begin() as db:
        db.get(Delivery, delivery_id).status = 'failed'
    assert client.post('/api/deliveries/' + delivery_id + '/retry', headers=headers).status_code == 403
    with factory.begin() as db:
        db.get(Role, 'operator').permissions = list(PERMISSIONS)
    assert client.post('/api/deliveries/' + delivery_id + '/retry', headers=headers).status_code == 200
    set_grant(factory, history_scope='own')
    assert client.get('/api/adjustments/' + batch).status_code == 404
    assert client.post('/api/adjustments/' + batch + '/recall', headers=headers).status_code == 404


@pytest.mark.parametrize('permission', ['history.recall', 'history.retry', 'ledgers.export'])
def test_optional_actions_revoked_for_own_records(client, factory, settings, when, permission):
    batch = submit(factory, settings, when, request(), user='operator')
    with factory.begin() as db:
        delivery = db.scalar(select(Delivery))
        delivery_id = delivery.id
        delivery.status = 'sent'; delivery.message_id = 'om_permission'; delivery.sent_at = when
    headers = login(client, factory, 'operator')
    with factory.begin() as db:
        r = db.get(Role, 'operator')
        r.permissions = [p for p in r.permissions if p != permission]
    endpoint = {'history.recall': '/api/adjustments/' + batch + '/recall',
                'history.retry': '/api/deliveries/' + delivery_id + '/retry',
                'ledgers.export': '/api/score-ledgers/export'}[permission]
    response = client.get(endpoint) if permission == 'ledgers.export' else client.post(endpoint, headers=headers)
    assert response.status_code == 403


def test_core_transaction_rechecks_revocation_and_accepted_delivery_continues(factory, settings, when):
    with factory.begin() as db:
        preview = create_preview(db, 'operator', request(), settings, when)
    batch = submit(factory, settings, when, request(person_ids=['b']), user='operator')
    # 保留旧会话里缓存的员工和角色，撤销功能后核心写入仍必须拒绝。
    with factory() as db:
        stale = db.get(Employee, 'operator')
        db.get(Role, 'operator')
        with factory.begin() as revoke:
            revoke.get(Role, 'operator').permissions = []
        with pytest.raises(HTTPException) as error:
            commit_preview(db, 'operator', preview['preview_token'], 'key', settings, when)
        assert error.value.status_code == 403
        db.rollback()
        with pytest.raises(HTTPException):
            request_recall(db, stale.id, batch_id=batch, when=when)
        db.rollback()
        delivery_id = db.scalar(select(Delivery.id))
        with pytest.raises(HTTPException):
            retry_delivery(db, delivery_id, stale, when)
    with factory.begin() as db:
        from app.db import now_utc
        assert claim_delivery(db, settings, now_utc() + timedelta(seconds=1)) is not None


def test_owner_bootstrap_independent_partial_progress_and_missing_config_notice(client, factory, settings, monkeypatch):
    settings.initial_admin_user_ids = 'staff-a,staff-b'
    with factory.begin() as db:
        db.get(SystemState, 1).bootstrap_done = True
        db.get(Employee, 'a').user_id = 'staff-a'
        bootstrap_owners(db, settings, lock_state(db))
    set_grant(factory, 'a', role='none')
    with factory.begin() as db:
        db.get(Employee, 'b').user_id = 'staff-b'
        bootstrap_owners(db, settings, lock_state(db))
    with factory() as db:
        assert db.get(Employee, 'a').role == 'none'
        assert db.get(Employee, 'b').role == 'owner'
        assert db.get(SystemState, 1).owner_bootstrap_done
        assert db.scalar(select(func.count()).select_from(PermissionAudit)) == 2
    # 登录 /me 可直接从已同步目录初始化，不必等待下一次定时同步。
    with factory.begin() as db:
        state = db.get(SystemState, 1)
        state.owner_bootstrap_done = False; state.owner_bootstrap_ids = []
    monkeypatch.setattr(auth.settings, 'initial_admin_user_ids', 'staff-a')
    login(client, factory, 'a')
    assert client.get('/api/auth/me').json()['role'] == 'owner'
    assert client.get('/api/auth/me').json()['can_configure_roles']


def test_concurrent_custom_role_deletion_and_grant(factory):
    owner(factory)
    with factory.begin() as db:
        db.add(Role(id='custom', name='并发角色', permissions=[]))
    barrier = Barrier(2)
    def run(action):
        with factory() as db:
            actor = db.get(Employee, 'admin')
            barrier.wait()
            try:
                if action == 'delete':
                    delete_role('custom', actor, db)
                else:
                    update_grant('a', GrantRequest(role='custom'), actor, db)
                return 200
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ['delete', 'grant']))
    assert results.count(200) == 1
    with factory() as db:
        assert db.get(Employee, 'a').role != 'custom' or db.get(Role, 'custom')


def test_role_permissions_apply_to_existing_session_and_preview_is_company_wide(client, factory, settings, when):
    with factory.begin() as db:
        db.add(Role(id='score-only', name='仅记分', permissions=['adjustments.write']))
    set_grant(factory, role='score-only', ledger_scope='departments', ledger_department_ids=['rd'])
    headers = login(client, factory, 'operator')
    assert client.get('/api/auth/me').json()['permissions'] == ['adjustments.write']
    assert not client.get('/api/auth/me').json()['can_manage']
    # 明细授权部门不限制记分和预览总分。
    body = request(person_ids=['b']).model_dump()
    preview = client.post('/api/adjustments/preview', headers=headers, json=body)
    assert preview.status_code == 200 and preview.json()['rows'][0]['before_total'] == 60
    with factory.begin() as db:
        db.get(Role, 'score-only').permissions = ['ledgers.read']
    assert client.get('/api/auth/me').json()['permissions'] == ['ledgers.read']
    assert client.post('/api/adjustments', headers=headers, json={'preview_token': preview.json()['preview_token'], 'idempotency_key': 'revoked'}).status_code == 403
    assert client.get('/api/score-ledgers?month=2026-10').status_code == 200
    assert client.get('/api/adjustments').status_code == 403
    assert client.get('/api/score-ledgers/export').status_code == 403


def test_owner_setup_notices_do_not_promote_other_admins(client, factory, monkeypatch):
    login(client, factory)
    monkeypatch.setattr(auth.settings, 'initial_admin_user_ids', '')
    assert 'INITIAL_ADMIN_USER_IDS' in client.get('/api/auth/me').json()['owner_notice']
    monkeypatch.setattr(auth.settings, 'initial_admin_user_ids', 'unmatched-user-id')
    assert '尚未匹配' in client.get('/api/auth/me').json()['owner_notice']
    with factory() as db:
        assert db.get(Employee, 'admin').role == 'admin'
        assert not db.get(SystemState, 1).owner_bootstrap_done
