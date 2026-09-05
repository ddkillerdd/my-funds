"""Stage D 后端 API 合同测试。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.schemas.holding import SimpleImportPreviewRequest, SimpleImportResult, SimpleImportRecord
from backend.schemas.holding_change import HoldingChangeResponse
from backend.services.holding_service import HoldingService


class _ScalarResult:
    """提供预览查询所需的单行结果。"""

    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_preview_returns_nav_and_shares_without_session_writes(monkeypatch):
    """验证预览返回名称/净值/日期/份额，且 Session 无写入。"""
    fund = SimpleNamespace(fund_code="000001", fund_name="虚构基金", latest_nav=Decimal("2"), latest_nav_date=date(2026, 9, 4))

    class Db:
        adds = flushes = commits = 0
        def execute(self, _statement):
            return _ScalarResult(fund)
        def add(self, _value):
            self.adds += 1
        def flush(self):
            self.flushes += 1
        def commit(self):
            self.commits += 1

    db = Db()
    result = HoldingService(db).preview_simple_import(SimpleImportPreviewRequest(
        fund_code="000001", market_value=Decimal("10"), platform="平台A", share_date=date(2026, 9, 5)
    ))
    assert result.fund_name == "虚构基金"
    assert result.latest_nav == Decimal("2")
    assert result.estimated_shares == Decimal("5")
    assert (db.adds, db.flushes, db.commits) == (0, 0, 0)


def test_preview_failure_does_not_create_placeholder(monkeypatch):
    """验证远端基金信息失败返回错误且不写入占位基金或持仓。"""
    class Db:
        adds = commits = 0
        def execute(self, _statement):
            return _ScalarResult(None)
        def add(self, _value):
            self.adds += 1
        def commit(self):
            self.commits += 1

    monkeypatch.setattr("backend.services.holding_service.fetch_fund_info", lambda _code: None)
    db = Db()
    with pytest.raises(ValueError, match="信息获取失败"):
        HoldingService(db).preview_simple_import(SimpleImportPreviewRequest(
            fund_code="000001", market_value=Decimal("10"), platform="平台A", share_date=date(2026, 9, 5)
        ))
    assert db.adds == db.commits == 0


def test_simple_result_lists_are_isolated_and_errors_have_platform():
    """验证批量结果列表隔离，并要求错误带平台身份。"""
    first = SimpleImportResult()
    second = SimpleImportResult()
    first.errors.append({"fund_code": "000001", "platform": "平台A", "message": "失败"})
    assert second.errors == []
    assert first.errors[0]["platform"] == "平台A"
    result = HoldingService(SimpleNamespace()).simple_import([
        SimpleImportRecord(fund_code="000001", market_value=Decimal("10"), platform="")
    ])
    assert result.errors[0]["platform"] == ""


def test_operation_history_contract_has_source_and_import_id():
    """验证统一操作历史可表达 manual/quick 空 import_id 与 file 非空 import_id。"""
    manual = HoldingChangeResponse(id=1, fund_code="000001", platform="平台A", change_type="new", shares_before=0, shares_after=1, shares_delta=1, business_date=date(2026, 9, 5), source_type="manual")
    file_item = HoldingChangeResponse(id=2, fund_code="000002", platform="平台B", change_type="increase", shares_before=1, shares_after=2, shares_delta=1, business_date=date(2026, 9, 4), source_type="file", import_id=9)
    assert manual.import_id is None
    assert file_item.import_id == 9


def test_operation_history_queries_stable_descending_order_and_limit():
    """验证 service 真实查询使用业务日期/id 倒序且限制最多 100 条。"""
    event = SimpleNamespace(id=2, import_id=9, holding_id=1, fund_code="000002", fund_name="虚构", platform="平台B", change_type="increase", shares_before=Decimal("1"), shares_after=Decimal("2"), shares_delta=Decimal("1"), nav_at_change=None, mv_before=None, mv_after=None, business_date=date(2026, 9, 4), source_type="file", created_at=None)
    class Db:
        def __init__(self):
            self.statement = None
        def execute(self, statement):
            self.statement = statement
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [event]))
    db = Db()
    result = HoldingService(db).get_operation_history(999)
    statement = str(db.statement).lower()
    assert result[0].import_id == 9
    assert "business_date desc" in statement and "id desc" in statement
    assert "limit" in statement


def test_preview_and_import_share_the_same_resolver(monkeypatch):
    """验证预览与真实快捷导入都经过同一个只读基金解析函数。"""
    calls = []
    service = HoldingService(SimpleNamespace())
    resolved = (SimpleNamespace(fund_code="000001", fund_name="旧名", latest_nav=Decimal("0")), SimpleNamespace(fund_name="统一名称", latest_nav=Decimal("2"), latest_nav_date=date(2026, 9, 4)), "统一名称", Decimal("2"), date(2026, 9, 4))
    service._resolve_simple_fund_data = lambda record: (calls.append(record.fund_code) or resolved)
    preview = service.preview_simple_import(SimpleImportPreviewRequest(fund_code="000001", market_value=Decimal("10"), platform="平台A", share_date=date(2026, 9, 5)))
    assert preview.fund_name == "统一名称" and preview.latest_nav == Decimal("2")
    assert calls == ["000001"]


def test_simple_import_existing_fund_persists_final_history_nav(monkeypatch):
    """验证已有 Fund 使用共同解析器最终名称、历史 NAV/日期并写入持仓。"""
    fund = SimpleNamespace(fund_code="000001", fund_name="基金000001", latest_nav=Decimal("0"), latest_nav_date=None)
    history = SimpleNamespace(unit_nav=Decimal("2"), nav_date=date(2026, 9, 4))
    holding = SimpleNamespace(
        id=3, fund_code="000001", platform="平台A", fund_account="平台A_000001",
        shares=Decimal("1"), market_value=Decimal("2"), status=1,
        nav_on_import=None, nav_date=None, last_import_id=8, source_type="file",
    )

    class Db:
        def __init__(self):
            self.calls = 0
            self.added = []
        def execute(self, _statement):
            self.calls += 1
            return _ScalarResult([fund, history, holding][self.calls - 1])
        def add(self, value):
            self.added.append(value)
        def flush(self):
            pass

    monkeypatch.setattr("backend.services.holding_service.fetch_fund_info", lambda _code: SimpleNamespace(fund_name="远端名称", latest_nav=Decimal("0"), latest_nav_date=None))
    db = Db()
    service = HoldingService(db)
    service._to_response = lambda current, current_fund: SimpleNamespace(holding=current, fund=current_fund)
    result = service._simple_import_one(SimpleImportRecord(fund_code="000001", market_value=Decimal("10"), platform="平台A", share_date=date(2026, 9, 5)))
    assert result.holding is holding
    assert fund.fund_name == "远端名称"
    assert fund.latest_nav == Decimal("2") and fund.latest_nav_date == date(2026, 9, 4)
    assert holding.nav_on_import == Decimal("2") and holding.nav_date == date(2026, 9, 4)
    assert holding.shares == Decimal("5")
