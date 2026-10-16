"""渠道日报只读预览的合成测试，禁止真实数据库、模型和邮件。"""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import advisor
from backend.database import get_db
from backend.services.decision_delivery_service import build_delivery_preview
from backend.services.purchase_channel_service import plan_purchase


NOW = datetime(2026, 10, 15, 14, 20, tzinfo=timezone(timedelta(hours=8)))


def confirmed_report():
    """构造当天有效、含渠道及预算门禁的合成报告。"""
    quote = {
        "fund_code": "000001", "platform": "合成平台", "payment_method": "合成支付",
        "purchase_status": "open", "account_eligible": True,
        "evidence_scope": "account_confirmed", "source": "合成证据",
        "observed_at": "2026-10-15T14:15:00+08:00", "min_purchase_rmb": "1",
        "daily_remaining_rmb": "100", "subscription_fee_rate_pct": "0.15",
    }
    return {
        "actions": [{"fund_code": "000001", "fund_name": "合成基金", "action": "buy", "action_amount": 20,
                     "raw_action_amount": 50, "policy_status": "allowed",
                     "purchase_check": plan_purchase("000001", 20, [quote], NOW),
                     "reason": "绝不能直接展示的原始买入50元指令"}],
        "execution_policy": {"purchase_channel_gate": True, "data_quality_ready": True,
                             "daily_buy_remaining_rmb": 20, "monthly_buy_remaining_rmb": 200},
        "degradation": {"any": False}, "completeness": {"data_quality": "good"},
    }


def preview(data=None, **kwargs):
    """固定时钟和数据库UTC创建时间，不连接任何外部系统。"""
    return build_delivery_preview(data or confirmed_report(), 7, datetime(2026, 10, 15, 6, 10), now=NOW, budget_rechecked=True, **kwargs)


def test_readonly_mail_preview_exists_without_triggering_report_or_send(monkeypatch):
    """缺失只读预览应先失败；正式实现后不得调用生成报告或发送邮件。"""
    row = SimpleNamespace(
        id=7, created_at=datetime(2026, 10, 15, 6, 10),
        report_json=json.dumps({"actions": [], "degradation": {"any": False}, "completeness": {"data_quality": "good"}}),
    )

    class ReadOnlyDB:
        """仅提供读取报告的查询链，不提供提交或写入方法。"""

        def query(self, model):
            """返回查询替身。"""
            return self

        def filter(self, *conditions):
            """保留过滤链。"""
            return self

        def first(self):
            """返回合成报告。"""
            return row

    app = FastAPI()
    app.include_router(advisor.router, prefix="/api/advisor")
    app.dependency_overrides[get_db] = lambda: ReadOnlyDB()
    with TestClient(app) as client:
        response = client.get("/api/advisor/report/7/mail-preview")
    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert data["email_sent"] is False
    assert data["report_generated"] is False
    assert data["holdings_updated"] is False


def test_valid_preview_recomputes_fees_without_mutating_or_showing_raw_candidates():
    """只展示最终20元及重新计算的费用，不泄漏原始50元建议。"""
    data = confirmed_report()
    before = deepcopy(data)
    data["actions"][0]["purchase_check"]["estimated_fee_rmb"] = 9
    result = preview(data)
    assert result["delivery_actions"][0]["payment_rmb"] == 20
    assert result["delivery_actions"][0]["estimated_fee_rmb"] == 0.03
    assert "19.97" in result["html"] and "0.03" in result["html"]
    assert "原始买入50元" not in result["html"]
    assert data["actions"][0]["purchase_check"]["estimated_fee_rmb"] == 9
    assert before["actions"][0]["action_amount"] == data["actions"][0]["action_amount"]


def test_blocked_legacy_stale_and_degraded_previews_all_zero():
    """原门禁拦截、旧报告、过期报告或质量降级均不恢复正向金额。"""
    for change in ("legacy", "blocked", "degraded", "expired", "public"):
        data = confirmed_report()
        if change == "legacy":
            data.pop("execution_policy")
        elif change == "blocked":
            data["actions"][0]["policy_status"] = "blocked"
        elif change == "degraded":
            data["degradation"]["any"] = True
        elif change == "expired":
            data["actions"][0]["purchase_check"]["observed_at"] = "2026-10-15T13:00:00+08:00"
        else:
            data["actions"][0]["purchase_check"]["evidence_scope"] = "public_only"
        result = preview(data)
        assert result["nonzero_action_count"] == 0, change
        assert "今日不操作" in result["html"]
        assert "原始买入50元" not in result["html"]


def test_send_time_and_current_budget_are_hard_bounds():
    """发送前必须复核预算，超过14:45或报告过期只能零金额。"""
    data = confirmed_report()
    data["execution_policy"]["monthly_buy_remaining_rmb"] = 3
    assert preview(data)["delivery_actions"][0]["payment_rmb"] == 3
    for now in (NOW.replace(hour=15), NOW + timedelta(days=1), NOW.replace(hour=13)):
        result = build_delivery_preview(data, 7, datetime(2026, 10, 15, 6, 10), now=now, budget_rechecked=True)
        assert result["nonzero_action_count"] == 0
    result = build_delivery_preview(data, 7, datetime(2026, 10, 15, 6, 10), now=NOW)
    assert result["nonzero_action_count"] == 0


def test_no_multiple_buy_or_unverified_redemption_and_html_is_escaped():
    """多只加仓和未核验赎回都不生成执行金额，动态内容始终转义。"""
    data = confirmed_report()
    data["actions"].append(deepcopy(data["actions"][0]))
    assert preview(data)["nonzero_action_count"] == 0
    data = confirmed_report()
    data["actions"][0]["fund_name"] = '<img src=x onerror="alert(1)">'
    assert "<img" not in preview(data)["html"]
    data["actions"][0].update(action="sell", action_amount=-10)
    result = preview(data)
    assert result["nonzero_action_count"] == 0
    assert "赎回费" in result["html"]


def test_missing_report_returns_404_and_invalid_json_returns_400():
    """读接口对缺失与坏报告失败关闭，不转向分析或发送路径。"""
    class Query:
        """提供可调整报告返回值的查询替身。"""

        row = None

        def query(self, *args):
            """继续查询。"""
            return self

        def filter(self, *args):
            """继续过滤。"""
            return self

        def first(self):
            """返回当前合成记录。"""
            return self.row

    db = Query()
    app = FastAPI()
    app.include_router(advisor.router, prefix="/api/advisor")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get('/api/advisor/report/7/mail-preview').status_code == 404
        db.row = SimpleNamespace(id=7, report_json='{bad', created_at=datetime.now())
        assert client.get('/api/advisor/report/7/mail-preview').status_code == 400


def test_boolean_amount_cannot_be_rendered_as_one_yuan_buy():
    """布尔值不是资金金额，不能被Python隐式转为1元付款。"""
    data = confirmed_report()
    data['actions'][0]['action_amount'] = True
    result = preview(data)
    assert result['nonzero_action_count'] == 0
    assert 'invalid_action' in result['delivery_actions'][0]['reasons']


def test_empty_legacy_report_still_explains_why_zero_and_bad_metadata_is_rejected():
    """空报告也说明不操作原因，异常门禁结构不被默认为通过。"""
    assert '旧报告未包含渠道门禁' in preview({'actions': []})['html']
    for field in ('execution_policy', 'degradation', 'completeness'):
        data = confirmed_report()
        data[field] = ['bad synthetic field']
        with pytest.raises(ValueError):
            preview(data)


@pytest.mark.parametrize('mode,expected', [('remaining', 3), ('blocked', 0), ('expired', 0), ('read_error', 0)])
def test_route_reads_current_budget_and_channel_without_restoring_old_candidates(monkeypatch, mode, expected):
    """真实预览路由重读预算和配置；读取失败、过期及旧拦截均不能放行。"""
    from backend.models.advisor_report import AdvisorReport
    from backend.models.trade_execution import TradeExecution

    data = confirmed_report()
    quote = deepcopy(data['actions'][0]['purchase_check'])
    if mode == 'blocked':
        # 即使旧数据错误地保留正数，原拦截也不能在重读预算时被放行。
        data['actions'][0].update(action_amount=20, raw_action_amount=50, policy_status='blocked')
    if mode == 'expired':
        quote['observed_at'] = '2026-10-15T13:00:00+08:00'
    row = SimpleNamespace(id=7, created_at=datetime(2026, 10, 15, 6, 10), report_json=json.dumps(data))

    class FrozenDatetime(datetime):
        """固定服务器时钟，不依赖测试执行当天。"""

        @classmethod
        def now(cls, tz=None):
            """返回固定上海时间。"""
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    class ReadQuery:
        """查询替身不提供任何写入方法。"""

        def __init__(self, model):
            """记录目标模型。"""
            self.model = model

        def filter(self, *conditions):
            """保留真实路由的过滤调用。"""
            return self

        def first(self):
            """只允许取报告。"""
            assert self.model is AdvisorReport
            return row

        def all(self):
            """模拟其他平台本月已付197元，不触发相邻交易日冷却。"""
            assert self.model is TradeExecution
            if mode == 'read_error':
                raise RuntimeError('synthetic budget read unavailable')
            return [SimpleNamespace(report_date='2026-10-01', actual_amount=197)]

    class ReadOnlyDB:
        """只允许报告、交易记录和配置SELECT。"""

        def query(self, model):
            """返回相应查询替身。"""
            return ReadQuery(model)

        def execute(self, statement):
            """验证配置读取语句为SELECT，不提供提交接口。"""
            assert statement.is_select
            return self

        def scalar_one_or_none(self):
            """返回合成的账户确认快照。"""
            return SimpleNamespace(value=json.dumps([quote]))

    monkeypatch.setattr(advisor, 'datetime', FrozenDatetime)
    app = FastAPI()
    app.include_router(advisor.router, prefix='/api/advisor')
    app.dependency_overrides[get_db] = lambda: ReadOnlyDB()
    with TestClient(app) as client:
        response = client.get('/api/advisor/report/7/mail-preview')
    assert response.status_code == 200
    result = response.json()
    assert result['delivery_actions'][0]['payment_rmb'] == expected
    assert result['email_sent'] is False and result['report_generated'] is False
    assert '原始买入50元' not in result['html']
    assert json.loads(row.report_json) == data
