"""公开渠道解析和失败关闭的合成测试，无真实基金页面或投资账户数据。"""
from datetime import datetime, timedelta, timezone

import httpx

from backend.services.public_purchase_source import fetch_current_public_options, parse_public_purchase_page
from backend.services.purchase_channel_service import plan_purchase


NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone(timedelta(hours=8)))


def page(code="000001", state="开放申购", rate="0.06%"):
    """生成含划线原费率、认购费和赎回费干扰项的虚构HTML。"""
    return f'''<h4>合成基金 ({code})</h4><h4>交易状态</h4><table>
    <tr><td>申购状态</td><td>{state}</td><td>赎回状态</td><td>开放赎回</td></tr></table>
    <h4>申购与赎回金额</h4><table><tr><td>申购起点</td><td>10.00元</td><td>日累计申购限额</td><td>100.00元</td></tr></table>
    <h4>认购费率</h4><table><tr><td>小于100万元</td><td>0.50%</td></tr></table>
    <h4>申购费率</h4><table><tr><td>小于100万元</td><td><s>0.60%</s></td><td>{rate}</td></tr>
    <tr><td>大于等于100万元，小于500万元</td><td>0.03%</td></tr></table>
    <h4>赎回费率</h4><table><tr><td>小于7天</td><td>1.50%</td></tr></table>'''


def test_public_rate_is_discounted_subscription_not_redemption_or_old_rate():
    """精确读取小额申购优惠费率，不能错用认购、原价或赎回费率。"""
    data = parse_public_purchase_page("000001", page(), now=NOW)
    assert data["subscription_fee_rate_pct"] == 0.06
    assert data["min_purchase_rmb"] == 10
    assert data["public_daily_limit_rmb"] == 100
    assert data["daily_remaining_rmb"] is None
    assert data["account_eligible"] is None
    assert plan_purchase("000001", 20, [data], NOW)["status"] == "blocked"


def test_paused_and_unlimited_public_info_do_not_become_account_capacity():
    """暂停、无限额字样和零费率均不等于账户已经可买。"""
    data = parse_public_purchase_page("000001", page(state="暂停申购", rate="0.00%").replace('100.00元', '无限额'), now=NOW)
    assert data["purchase_status"] == "paused"
    assert data["subscription_fee_rate_pct"] == 0
    assert data["public_daily_limit_rmb"] is None
    assert data["payment_rmb"] == 0


def test_wrong_identity_or_changed_markup_returns_unknown_not_guesses():
    """错基金、验证码页、字段变更不允许复用旧值。"""
    wrong = parse_public_purchase_page("000001", page(code="000002"), now=NOW)
    assert wrong["error_kind"] == "fund_identity_unverified"
    missing = parse_public_purchase_page("000001", page().replace("申购费率", "收费说明"), now=NOW)
    assert missing["subscription_fee_rate_pct"] is None
    assert missing["error_kind"] == "public_fields_incomplete"


def test_fetch_only_current_four_and_never_retries_or_leaks_error():
    """只查询允许代码，每只一次，失败不泄露响应内容或认证信息。"""
    calls = []

    def fetch(code):
        """模拟一个正常页面和一个网络失败。"""
        calls.append(code)
        if code == "018044":
            raise httpx.ConnectError("secret synthetic upstream error")
        return page(code)

    results = fetch_current_public_options(["013308", "013308", "018044", "999999", "http://127.0.0.1"], fetch_page=fetch, now=NOW)
    assert calls == ["013308", "018044"]
    assert results[1]["error_kind"] == "public_source_unavailable"
    assert "secret" not in str(results)
    assert all(item["is_trade_instruction"] is False for item in results)


def test_discount_cell_separator_does_not_hide_fee_or_allow_ambiguous_rates():
    """实际页面用竖线分隔原价和优惠价，移除原价后只接受唯一百分比。"""
    markup = page().replace('<td><s>0.60%</s></td><td>0.06%</td>', '<td><s>0.60%</s>|0.06%</td>')
    assert parse_public_purchase_page('000001', markup, now=NOW)['subscription_fee_rate_pct'] == 0.06
    ambiguous = markup.replace('|0.06%', '|0.06%|0.09%')
    assert parse_public_purchase_page('000001', ambiguous, now=NOW)['subscription_fee_rate_pct'] is None


def test_readonly_public_route_queries_only_active_codes_without_database_writes(monkeypatch):
    """真实路由只查询有效持仓代码，把新基金范围筛选留在公开适配器。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import advisor
    from backend.database import get_db
    from backend.services import public_purchase_source

    calls = []

    def synthetic_fetch(code):
        """只返回虚构公开页面，测试不联网。"""
        calls.append(code)
        return page(code)

    class ReadOnlyQuery:
        """不提供提交或持仓修改接口的查询替身。"""

        def query(self, field):
            """只接受基金代码列。"""
            assert field.key == 'fund_code'
            return self

        def filter(self, condition):
            """确认路由只纳入有效持仓。"""
            assert condition.right.value == 1
            return self

        def distinct(self):
            """继续去重查询。"""
            return self

        def all(self):
            """当前范围外代码不会触发公开抓取。"""
            return [('013308',), ('013308',), ('999999',)]

    monkeypatch.setattr(public_purchase_source, '_fetch_page', synthetic_fetch)
    app = FastAPI()
    app.include_router(advisor.router, prefix='/api/advisor')
    app.dependency_overrides[get_db] = lambda: ReadOnlyQuery()
    with TestClient(app) as client:
        response = client.get('/api/advisor/purchase-options/public')
    assert response.status_code == 200
    assert calls == ['013308']
    assert response.json()['account_verified'] is False
    assert response.json()['is_trade_instruction'] is False
