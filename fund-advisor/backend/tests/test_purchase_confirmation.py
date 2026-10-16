"""下单页当次确认的合成路由测试，不连接账户、不写数据库或发送邮件。"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import advisor
from backend.database import get_db
from backend.models.advisor_report import AdvisorReport
from backend.models.holding import FundHolding
from backend.models.trade_execution import TradeExecution


NOW = datetime(2026, 10, 15, 14, 20, tzinfo=timezone(timedelta(hours=8)))


def report_data():
    """构造仅因账户渠道未知而归零的虚构报告。"""
    return {
        'actions': [{'fund_code': '013308', 'fund_name': '合成基金', 'action': 'buy',
                     'action_amount': 0, 'raw_action_amount': 20, 'policy_status': 'blocked',
                     'policy_reasons': ['purchase_channel_unverified']}],
        'execution_policy': {'purchase_channel_gate': True, 'data_quality_ready': True},
        'degradation': {'any': False}, 'completeness': {'data_quality': 'good'},
    }


def confirmation():
    """虚构下单页信息，不含真实账户号、凭据或交易请求。"""
    return {
        'fund_code': '013308', 'platform': '支付宝', 'payment_method': '银行卡',
        'purchase_status': 'open', 'account_eligible': True,
        'subscription_fee_rate_pct': '0.15', 'min_purchase_rmb': '1.00',
        'verified_capacity_rmb': '20.00', 'observed_at': '2026-10-15T14:18:00+08:00',
        'confirmed_by_user': True,
    }


class ReadOnlyDB:
    """只提供报告、有效持仓代码和实际支出查询，不提供写入方法。"""

    def __init__(self, data=None, spent=0):
        """固定合成报告和本月跨平台已付款。"""
        self.row = SimpleNamespace(id=7, report_json=json.dumps(data or report_data()), created_at=datetime(2026, 10, 15, 6, 10))
        self.spent = spent
        self.queries = []

    def query(self, model):
        """每个查询使用独立对象，避免链式查询状态互相覆盖。"""
        self.queries.append(model)
        db = self

        class Query:
            """仅模拟SELECT。"""

            def filter(self, *conditions):
                """记录中无需真实SQL执行。"""
                return self

            def distinct(self):
                """支持有效持仓代码去重。"""
                return self

            def first(self):
                """只允许读取合成报告。"""
                assert model is AdvisorReport
                return db.row

            def all(self):
                """返回有效代码或跨平台真实支出替身。"""
                if model is TradeExecution:
                    return [SimpleNamespace(report_date='2026-10-01', actual_amount=db.spent)]
                assert model is FundHolding.fund_code
                return [('013308',)]

        return Query()


def client_for(db, monkeypatch):
    """只装载路由，禁用真实应用启动、数据库与定时器。"""
    class FrozenDatetime(datetime):
        """固定服务器时间。"""

        @classmethod
        def now(cls, tz=None):
            """返回固定上海时钟。"""
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(advisor, 'datetime', FrozenDatetime)
    app = FastAPI()
    app.include_router(advisor.router, prefix='/api/advisor')
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_confirmation_preview_is_stateless_and_splits_gross_payment(monkeypatch):
    """当次确认解开渠道未知，但不得写报告、配置、持仓或邮件。"""
    db = ReadOnlyDB()
    before = db.row.report_json
    with client_for(db, monkeypatch) as client:
        response = client.post('/api/advisor/report/7/purchase-preview', json=confirmation())
    assert response.status_code == 200
    data = response.json()
    action = data['delivery_actions'][0]
    assert action['payment_rmb'] == 20
    assert action['estimated_fee_rmb'] == 0.03
    assert action['estimated_net_investment_rmb'] == 19.97
    assert data['confirmation_saved'] is False
    assert data['readonly'] is True and data['email_sent'] is False
    assert db.row.report_json == before


@pytest.mark.parametrize('spent,expected', [(197, 3), (200, 0), (210, 0)])
def test_confirmation_does_not_refill_monthly_budget(monkeypatch, spent, expected):
    """确认渠道只补证据，不增加跨平台月度额度。"""
    with client_for(ReadOnlyDB(spent=spent), monkeypatch) as client:
        response = client.post('/api/advisor/report/7/purchase-preview', json=confirmation())
    assert response.status_code == 200
    assert response.json()['delivery_actions'][0]['payment_rmb'] == expected
    if expected == 0:
        assert response.json()['delivery_actions'][0]['reasons']


@pytest.mark.parametrize('patch', [
    {'purchase_status': 'paused'}, {'purchase_status': 'unknown'}, {'account_eligible': False},
    {'subscription_fee_rate_pct': None}, {'min_purchase_rmb': None}, {'verified_capacity_rmb': None},
    {'verified_capacity_rmb': '0'}, {'min_purchase_rmb': '30'},
    {'observed_at': '2026-10-15T13:00:00+08:00'}, {'observed_at': '2026-10-15T14:21:00+08:00'},
    {'observed_at': '2026-10-14T14:18:00+08:00'},
])
def test_unknown_paused_stale_or_insufficient_information_stays_zero(monkeypatch, patch):
    """信息不全、暂停、过期、未来和额度不足不能被手动确认变成可买。"""
    with client_for(ReadOnlyDB(), monkeypatch) as client:
        response = client.post('/api/advisor/report/7/purchase-preview', json=confirmation() | patch)
    assert response.status_code == 200
    assert response.json()['nonzero_action_count'] == 0
    assert response.json()['delivery_actions'][0]['reasons']


@pytest.mark.parametrize('patch', [
    {'confirmed_by_user': False}, {'confirmed_by_user': 'true'}, {'account_eligible': 1},
    {'subscription_fee_rate_pct': True}, {'subscription_fee_rate_pct': 'NaN'},
    {'subscription_fee_rate_pct': 'Infinity'}, {'subscription_fee_rate_pct': '-1'},
    {'verified_capacity_rmb': '20.01'}, {'verified_capacity_rmb': '0.001'},
    {'observed_at': '2026-10-15T14:18:00'}, {'evidence_scope': 'account_confirmed'},
    {'account_number': 'synthetic-not-a-real-account'}, {'payment_method': '自由文本'},
    {'platform': '天天基金', 'payment_method': '余额宝'},
])
def test_malformed_or_unconfirmed_input_rejected_before_database_query(monkeypatch, patch):
    """不接收身份或秘密字段，格式错误不查询数据库。"""
    db = ReadOnlyDB()
    with client_for(db, monkeypatch) as client:
        response = client.post('/api/advisor/report/7/purchase-preview', json=confirmation() | patch)
    assert response.status_code == 422
    assert not db.queries


@pytest.mark.parametrize('reason', ['monthly_buy_limit_reached', 'consecutive_trading_day_cooldown', 'single_fund_daily_limit', 'analysis_degraded'])
def test_user_confirmation_never_overrides_non_channel_block(monkeypatch, reason):
    """只允许解除渠道未知，不能恢复冷却、单只、预算或质量拦截候选。"""
    saved = report_data()
    saved['actions'][0]['policy_reasons'] = [reason]
    with client_for(ReadOnlyDB(saved), monkeypatch) as client:
        response = client.post('/api/advisor/report/7/purchase-preview', json=confirmation())
    assert response.json()['nonzero_action_count'] == 0
    assert response.json()['delivery_actions'][0]['reasons']


def test_degradation_legacy_inactive_and_bad_read_are_fail_closed(monkeypatch):
    """降级报告、旧报告、非当前基金和读取故障不能放行。"""
    saved = report_data()
    saved['degradation']['any'] = True
    with client_for(ReadOnlyDB(saved), monkeypatch) as client:
        assert client.post('/api/advisor/report/7/purchase-preview', json=confirmation()).json()['nonzero_action_count'] == 0
    saved.pop('execution_policy')
    with client_for(ReadOnlyDB(saved), monkeypatch) as client:
        assert client.post('/api/advisor/report/7/purchase-preview', json=confirmation()).status_code == 409
    with client_for(ReadOnlyDB(), monkeypatch) as client:
        assert client.post('/api/advisor/report/7/purchase-preview', json=confirmation() | {'fund_code': '999999'}).status_code == 422


def test_read_failure_does_not_expose_database_details_or_restore_amount(monkeypatch):
    """预算故障只返回脱敏拒绝，不泄漏错误或转向其他写入流程。"""
    class BrokenDB(ReadOnlyDB):
        """仅预算查询抛出含敏感占位字样的错误。"""

        def query(self, model):
            """报告和持仓读取正常。"""
            if model is TradeExecution:
                raise RuntimeError('synthetic-secret-do-not-expose')
            return super().query(model)

    with client_for(BrokenDB(), monkeypatch) as client:
        response = client.post('/api/advisor/report/7/purchase-preview', json=confirmation())
    assert response.status_code == 503
    assert 'synthetic-secret' not in response.text


def test_preview_expiry_respects_old_report_not_just_confirmation_time(monkeypatch):
    """新确认不能延长旧报告有效期；重复试算也不改原确认时间。"""
    db = ReadOnlyDB()
    db.row.created_at = datetime(2026, 10, 15, 5, 52)
    with client_for(db, monkeypatch) as client:
        data = client.post('/api/advisor/report/7/purchase-preview', json=confirmation()).json()
    assert data['valid_until'] == '2026-10-15T14:22:00+08:00'


def test_month_boundary_database_query_keeps_previous_weekday_cooldown():
    """内存SQLite重现月初漏查上月最后交易日，绝不接触服务器数据库。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.schemas.purchase_confirmation import PurchaseConfirmation
    from backend.services.execution_policy import apply_execution_policy_from_db
    from backend.services.purchase_confirmation_service import prepare_confirmation_report

    engine = create_engine('sqlite:///:memory:')
    TradeExecution.__table__.create(engine)
    clock = datetime(2026, 6, 1, 14, 20, tzinfo=NOW.tzinfo)
    quote = PurchaseConfirmation(**(confirmation() | {'observed_at': '2026-06-01T14:18:00+08:00'})).as_quote()
    with Session(engine) as db:
        db.add(TradeExecution(id=1, report_id=1, report_date='2026-05-29', fund_code='013308', actual_amount=10))
        db.commit()
        report = prepare_confirmation_report(report_data(), '013308')
        result = apply_execution_policy_from_db(db, report, now=clock, confirmed_quotes=[quote])
        assert result['execution_policy']['monthly_buy_spent_rmb'] == 0
        assert result['execution_policy']['cooldown_active'] is True
        assert result['actions'][0]['action_amount'] == 0
    engine.dispose()
