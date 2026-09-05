"""持仓导入正确性回归测试。"""

from datetime import date, datetime
from decimal import Decimal

from backend.services.excel_parser import _parse_date, parse_excel
from backend.schemas.holding import HoldingCreate, SimpleImportRecord, HoldingChangeRequest
from backend.services.holding_service import HoldingService, build_holding_change
from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.holding_change import HoldingChange
from backend.services.nav_fetcher import FundInfo, NavData
from backend.services.nav_service import NavService
from backend.services.import_service import ImportService
from backend.services.calendar_service import CalendarService
from backend.services.snapshot_service import SnapshotService


# 验证 Excel 的数字基金代码恢复为六位字符串。
def test_excel_parser_preserves_six_digit_fund_code():
    import openpyxl

    path = __import__("pathlib").Path(__file__).with_name(".holding-ingestion-test.xlsx")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    headers = ["序号", "基金代码", "基金名称", "份额类别", "基金管理人", "基金账户", "销售机构", "交易账户", "持有份额", "份额日期", "基金净值", "净值日期", "资产情况", "结算币种", "分红方式"]
    sheet.append(["基金持仓"])
    sheet.append([])
    sheet.append([])
    sheet.append([])
    sheet.append(headers)
    sheet.append([1, 1, "测试基金", "前收费", "测试管理人", "账户", "平台", "交易账户", 10, date(2026, 9, 4), Decimal("1.2"), date(2026, 9, 3), 12, "人民币", None])
    workbook.save(path)
    workbook.close()
    try:
        holdings, errors, _ = parse_excel(path)
        assert not errors
        assert holdings[0].fund_code == "000001"
    finally:
        path.unlink(missing_ok=True)


# 验证 Excel 的 datetime 单元格按日期解析而不是被当作无效字符串。
def test_excel_parser_accepts_datetime_cell():
    assert _parse_date(datetime(2026, 9, 4)) == date(2026, 9, 4)


# 验证快捷导入的默认业务日期在每次请求创建时计算。
def test_simple_import_default_date_uses_factory():
    record = SimpleImportRecord(fund_code="000001", market_value=Decimal("10"))
    assert SimpleImportRecord.model_fields["share_date"].default_factory is not None
    assert isinstance(record.share_date, date)


class _ImportResult:
    """提供快捷导入测试所需的最小查询结果。"""

    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RowsResult:
    """提供列表查询所需的最小结果对象。"""

    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _ImportSession:
    """记录快捷导入写入对象并返回预设查询结果。"""

    def __init__(self, fund):
        self.results = iter([_ImportResult(fund), _ImportResult(None)])
        self.added = []

    def execute(self, _statement):
        return next(self.results)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 1
            if getattr(value, "currency", None) is None:
                value.currency = "人民币"
            if getattr(value, "status", None) is None:
                value.status = 1

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, _value):
        pass


class _EntrySession:
    """模拟真实 service 入口所需的查询、flush、提交和回滚边界。"""

    def __init__(self, values, fail_event=False, fail_flush=False):
        self.values = iter(values)
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_event = fail_event
        self.fail_flush = fail_flush

    def execute(self, _statement):
        return _ImportResult(next(self.values))

    def add(self, value):
        if self.fail_event and isinstance(value, HoldingChange):
            raise RuntimeError("虚构事件写入失败")
        self.added.append(value)

    def flush(self):
        if self.fail_flush:
            raise RuntimeError("虚构 flush 失败")
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = len(self.added)
            if getattr(value, "status", None) is None:
                value.status = 1
            if getattr(value, "currency", None) is None:
                value.currency = "人民币"

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _value):
        pass


def _holding_for_entry(**overrides):
    """创建真实入口测试使用的虚构持仓。"""
    values = {
        "id": 1, "fund_code": "000101", "fund_name": "虚构基金",
        "share_type": "前收费", "management_company": None,
        "platform": "平台A", "fund_account": "账户A", "trade_account": "账户A",
        "shares": Decimal("5"), "share_date": date(2026, 9, 4),
        "nav_on_import": Decimal("2"), "nav_date": date(2026, 9, 4),
        "cost_nav": Decimal("1"), "market_value": Decimal("10"),
        "currency": "人民币", "dividend_mode": None, "last_import_id": None,
        "source_type": "manual", "status": 1, "created_at": None, "updated_at": None,
    }
    values.update(overrides)
    return type("Holding", (), values)()


# 验证快捷导入按平台生成稳定账户，且没有成本信息时不伪造 cost_nav。
def test_simple_import_uses_platform_identity_and_keeps_cost_unknown():
    fund = Fund(fund_code="000001", fund_name="测试基金", latest_nav=Decimal("2.0"))
    session = _ImportSession(fund)
    record = SimpleImportRecord(
        fund_code="000001",
        market_value=Decimal("100"),
        platform="天天基金",
        share_date=date(2026, 9, 4),
    )

    result = HoldingService(session)._simple_import_one(record)
    holding = session.added[0]

    assert result.shares == Decimal("50")
    assert holding.fund_account == "天天基金_000001"
    assert holding.cost_nav is None


# 验证未知基金只有补全公开信息成功后才允许落库。
def test_unknown_fund_is_enriched_before_insert(monkeypatch):
    monkeypatch.setattr(
        "backend.services.holding_service.fetch_fund_info",
        lambda _code: FundInfo("000002", "公开基金", Decimal("1.25"), date(2026, 9, 3)),
    )
    session = _ImportSession(None)
    record = SimpleImportRecord(
        fund_code="000002", market_value=Decimal("100"), platform="平台B"
    )

    result = HoldingService(session)._simple_import_one(record)

    assert result.fund_name == "公开基金"
    assert result.shares == Decimal("80")
    assert session.added[0].fund_name == "公开基金"


# 验证公开基金信息失败时不产生占位 Fund 或零份额持仓。
def test_unknown_fund_failure_does_not_write_placeholder(monkeypatch):
    monkeypatch.setattr(
        "backend.services.holding_service.fetch_fund_info", lambda _code: None
    )
    session = _ImportSession(None)
    record = SimpleImportRecord(
        fund_code="000003", market_value=Decimal("100"), platform="平台C"
    )

    import pytest

    with pytest.raises(ValueError, match="信息获取失败"):
        HoldingService(session)._simple_import_one(record)
    assert session.added == []


# 验证关联 Fund 是持仓响应中基金名称的规范来源。
def test_response_prefers_fund_name():
    holding = type("Holding", (), {
        "id": 1, "fund_code": "000001", "fund_name": "旧名称", "share_type": None,
        "management_company": None, "platform": "平台", "fund_account": "账户",
        "trade_account": "账户", "shares": Decimal("1"), "share_date": date(2026, 9, 4),
        "nav_on_import": None, "nav_date": None, "cost_nav": None, "market_value": Decimal("1"),
        "currency": "人民币", "dividend_mode": None, "status": 1, "created_at": None,
        "updated_at": None,
    })()
    fund = Fund(fund_code="000001", fund_name="规范名称", latest_nav=Decimal("1"))
    response = HoldingService(_ImportSession(None))._to_response(holding, fund)
    assert response.fund_name == "规范名称"


# 验证 NAV 刷新保留遗留市值并按有效净值恢复份额。
def test_nav_refresh_repairs_zero_share_placeholder(monkeypatch):
    fund = Fund(fund_code="000004", fund_name="基金000004")
    active = type("Holding", (), {
        "fund_code": "000004", "fund_name": "000004", "shares": Decimal("0"),
        "market_value": Decimal("100"), "status": 1,
    })()
    closed = type("Holding", (), {
        "fund_code": "000004", "fund_name": "基金000004", "shares": Decimal("0"),
        "market_value": Decimal("200"), "status": 0,
    })()

    class Session:
        def execute(self, statement):
            text = str(statement)
            if "funds" in text:
                return _ImportResult(fund)
            return type("Rows", (), {"scalars": lambda self: type("Scalar", (), {"all": lambda self: [active]})()})()

    monkeypatch.setattr(
        "backend.services.nav_service.fetch_fund_info",
        lambda _code: FundInfo("000004", "规范基金", Decimal("2"), date(2026, 9, 4)),
    )
    NavService(Session())._update_fund_nav(
        NavData("000004", date(2026, 9, 4), Decimal("2"))
    )
    assert active.shares == Decimal("50")
    assert active.market_value == Decimal("100")
    assert active.fund_name == "规范基金"
    assert closed.shares == Decimal("0")
    assert closed.market_value == Decimal("200")


# 验证批次首条提交失败会回滚，后续记录仍继续处理。
def test_simple_import_rolls_back_failed_record_and_continues(monkeypatch):
    class BatchSession:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        def commit(self):
            self.commits += 1
            if self.commits == 1:
                raise RuntimeError("虚构数据库失败")

        def rollback(self):
            self.rollbacks += 1

    session = BatchSession()
    service = HoldingService(session)
    monkeypatch.setattr(service, "_simple_import_one", lambda _rec: "ok")
    records = [
        SimpleImportRecord(fund_code="000001", market_value=Decimal("10")),
        SimpleImportRecord(fund_code="000002", market_value=Decimal("10")),
    ]
    result = service.simple_import(records)
    assert result.success == 1
    assert len(result.errors) == 1
    assert session.rollbacks == 1
    assert session.commits == 2


# 验证同一基金在不同平台形成不同快捷持仓身份。
def test_same_fund_different_platforms_do_not_merge():
    fund = Fund(fund_code="000005", fund_name="测试基金", latest_nav=Decimal("2"))

    class Session(_ImportSession):
        def __init__(self):
            super().__init__(fund)
            self.accounts = []

        def add(self, value):
            super().add(value)
            if hasattr(value, "fund_account"):
                self.accounts.append(value.fund_account)

    first = Session()
    HoldingService(first)._simple_import_one(
        SimpleImportRecord(fund_code="000005", market_value=Decimal("10"), platform="平台A")
    )
    second = Session()
    HoldingService(second)._simple_import_one(
        SimpleImportRecord(fund_code="000005", market_value=Decimal("10"), platform="平台B")
    )
    assert first.accounts == ["平台A_000005"]
    assert second.accounts == ["平台B_000005"]


# 验证已有基金占位名称会在快捷导入前补全。
def test_existing_placeholder_fund_is_enriched(monkeypatch):
    monkeypatch.setattr(
        "backend.services.holding_service.fetch_fund_info",
        lambda _code: FundInfo("000006", "公开名称", Decimal("2.5"), date(2026, 9, 4)),
    )
    fund = Fund(fund_code="000006", fund_name="基金000006")
    session = _ImportSession(fund)
    result = HoldingService(session)._simple_import_one(
        SimpleImportRecord(fund_code="000006", market_value=Decimal("100"))
    )
    assert fund.fund_name == "公开名称"
    assert result.shares == Decimal("40")


# 验证 NAV 信息失败时遗留零份额和正市值完全保持不变。
def test_nav_info_failure_keeps_placeholder_holding_unchanged(monkeypatch):
    fund = Fund(fund_code="000007", fund_name="基金000007", latest_nav=Decimal("1.5"))
    holding = type("Holding", (), {
        "fund_code": "000007", "fund_name": "基金000007", "shares": Decimal("0"),
        "market_value": Decimal("88"), "status": 1,
    })()

    class Session:
        def execute(self, statement):
            text = str(statement)
            if "funds" in text:
                return _ImportResult(fund)
            return type("Rows", (), {"scalars": lambda self: type("Scalar", (), {"all": lambda self: [holding]})()})()

    monkeypatch.setattr("backend.services.nav_service.fetch_fund_info", lambda _code: None)
    NavService(Session())._update_fund_nav(
        NavData("000007", date(2026, 9, 4), Decimal("2"))
    )
    assert fund.fund_name == "基金000007"
    assert holding.shares == Decimal("0")
    assert holding.market_value == Decimal("88")


# 验证公开基金响应中的代码、名称、净值和时间戳异常会被拒绝。
def test_public_fund_info_rejects_invalid_response(monkeypatch):
    from backend.services import nav_fetcher

    class Response:
        text = 'fS_name = ""; Data_netWorthTrend = [{"x": 0, "y": 0}];'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(nav_fetcher.httpx, "get", lambda *args, **kwargs: Response())
    assert nav_fetcher.fetch_fund_info("bad") is None
    assert nav_fetcher.fetch_fund_info("000008") is None


# 验证统一事件辅助函数保留空导入关联和带符号份额差额。
def test_holding_change_helper_writes_signed_delta_and_business_fields():
    event = build_holding_change(
        holding_id=1, fund_code="000009", fund_name="虚构基金", platform="手工",
        change_type="decrease", shares_before=Decimal("10"),
        shares_after=Decimal("7"), shares_delta=Decimal("-3"),
        nav_at_change=Decimal("2"), mv_before=Decimal("20"),
        mv_after=Decimal("14"), business_date=date(2026, 9, 4),
        source_type="manual",
    )
    assert event.import_id is None
    assert event.shares_delta == Decimal("-3")
    assert event.business_date == date(2026, 9, 4)
    assert event.source_type == "manual"


# 验证 ORM 模型声明了 B1 所需的可空性和来源字段。
def test_b1_model_columns_have_required_nullability():
    assert FundHolding.__table__.c.source_type.nullable is False
    assert HoldingChange.__table__.c.import_id.nullable is True
    assert HoldingChange.__table__.c.business_date.nullable is False
    assert HoldingChange.__table__.c.source_type.nullable is False


# 验证手工新增真实入口写入 manual/new 事件。
def test_create_holding_entry_writes_manual_new_event():
    session = _EntrySession([None])
    HoldingService(session).create_holding(HoldingCreate(
        fund_code="000101", fund_name="虚构基金", platform="平台A",
        shares=Decimal("5"), share_date=date(2026, 9, 4),
        market_value=Decimal("10"), nav_on_import=Decimal("2"),
    ))
    events = [value for value in session.added if isinstance(value, HoldingChange)]
    assert events[0].source_type == "manual"
    assert events[0].change_type == "new"
    assert events[0].import_id is None


# 验证快捷新增和更新真实入口写 quick 事件及请求日期。
def test_simple_import_entry_writes_quick_new_and_update_events():
    fund = Fund(fund_code="000102", fund_name="虚构基金", latest_nav=Decimal("2"))
    new_session = _EntrySession([fund, None])
    service = HoldingService(new_session)
    service.simple_import([SimpleImportRecord(
        fund_code="000102", market_value=Decimal("10"), platform="平台A",
        share_date=date(2026, 9, 3),
    )])
    new_events = [value for value in new_session.added if isinstance(value, HoldingChange)]
    assert new_events[0].source_type == "quick"
    assert new_events[0].change_type == "new"
    assert new_events[0].business_date == date(2026, 9, 3)

    existing = _holding_for_entry(fund_code="000102", platform="平台A",
                                  fund_account="平台A_000102", trade_account="平台A_000102",
                                  shares=Decimal("5"), source_type="quick")
    update_session = _EntrySession([fund, existing])
    HoldingService(update_session).simple_import([SimpleImportRecord(
        fund_code="000102", market_value=Decimal("20"), platform="平台A",
        share_date=date(2026, 9, 4),
    )])
    update_events = [value for value in update_session.added if isinstance(value, HoldingChange)]
    assert update_events[0].change_type == "increase"
    assert update_events[0].shares_delta > 0


# 验证普通减仓和超额减仓清仓使用实际最终差值及最终市值。
def test_record_change_entry_uses_actual_clear_delta_and_mv():
    holding = _holding_for_entry()
    fund = Fund(fund_code="000101", fund_name="虚构基金", latest_nav=Decimal("2"))
    session = _EntrySession([holding, fund, fund])
    HoldingService(session).record_change(
        holding.id, HoldingChangeRequest(
            change_type="decrease", amount=Decimal("20"),
            business_date=date(2026, 9, 4),
        )
    )
    events = [value for value in session.added if isinstance(value, HoldingChange)]
    assert holding.shares == Decimal("0")
    assert holding.market_value == Decimal("0.0000")
    assert events[0].shares_delta == Decimal("-5")
    assert events[0].mv_after == Decimal("0.0000")


# 验证普通减仓仍保留活动状态并写负 delta。
def test_record_change_entry_normal_decrease_writes_negative_delta():
    holding = _holding_for_entry()
    fund = Fund(fund_code="000101", fund_name="虚构基金", latest_nav=Decimal("2"))
    session = _EntrySession([holding, fund, fund])
    HoldingService(session).record_change(
        holding.id, HoldingChangeRequest(
            change_type="decrease", amount=Decimal("4"),
            business_date=date(2026, 9, 4),
        )
    )
    event = next(value for value in session.added if isinstance(value, HoldingChange))
    assert holding.status == 1
    assert event.change_type == "decrease"
    assert event.shares_delta == Decimal("-2.0000")


# 验证手工变动接管文件持仓，并阻止后续文件快照误清仓。
def test_manual_change_takes_over_file_holding_from_snapshot_cleanup():
    holding = _holding_for_entry(source_type="file", last_import_id=77)
    fund = Fund(fund_code="000101", fund_name="虚构基金", latest_nav=Decimal("2"))
    change_session = _EntrySession([holding, fund, fund])
    HoldingService(change_session).record_change(
        holding.id, HoldingChangeRequest(change_type="increase", amount=Decimal("2"))
    )
    assert holding.source_type == "manual"
    assert holding.last_import_id is None

    class SnapshotSession:
        def __init__(self):
            self.added = []

        def execute(self, _statement):
            return _RowsResult([holding])

        def add(self, value):
            self.added.append(value)

        def flush(self):
            pass

    snapshot_session = SnapshotSession()
    _, _, removed, changes = ImportService(snapshot_session)._merge_holdings(
        [], 78, date(2026, 9, 5)
    )
    assert removed == 0
    assert changes == []
    assert holding.status == 1


# 验证新增入口 flush 失败时会回滚。
def test_create_holding_entry_rolls_back_on_flush_failure():
    session = _EntrySession([None], fail_flush=True)
    try:
        HoldingService(session).create_holding(HoldingCreate(
            fund_code="000105", fund_name="虚构基金", platform="平台A",
            shares=Decimal("1"), share_date=date(2026, 9, 4),
        ))
    except RuntimeError as exc:
        assert "flush 失败" in str(exc)
    else:
        raise AssertionError("应在 flush 失败时抛出异常")
    assert session.rollbacks == 1


# 验证加减仓入口 flush 失败时会回滚。
def test_record_change_entry_rolls_back_on_flush_failure():
    holding = _holding_for_entry()
    fund = Fund(fund_code="000101", fund_name="虚构基金", latest_nav=Decimal("2"))
    session = _EntrySession([holding, fund, fund], fail_flush=True)
    try:
        HoldingService(session).record_change(
            holding.id, HoldingChangeRequest(change_type="increase", amount=Decimal("2"))
        )
    except RuntimeError as exc:
        assert "flush 失败" in str(exc)
    else:
        raise AssertionError("应在 flush 失败时抛出异常")
    assert session.rollbacks == 1


# 验证删除真实入口与清仓事件同事务提交。
def test_delete_holding_entry_writes_manual_clear_event():
    holding = _holding_for_entry()
    session = _EntrySession([holding])
    HoldingService(session).delete_holding(holding.id)
    events = [value for value in session.added if isinstance(value, HoldingChange)]
    assert holding.status == 0
    assert events[0].change_type == "clear"
    assert events[0].shares_delta == Decimal("-5")
    assert session.commits == 1


# 验证重复删除被拒绝且不会生成第二条清仓事件。
def test_delete_holding_entry_rejects_duplicate_delete():
    holding = _holding_for_entry()
    session = _EntrySession([holding, holding])
    service = HoldingService(session)
    service.delete_holding(holding.id)
    try:
        service.delete_holding(holding.id)
    except ValueError as exc:
        assert "already cleared" in str(exc)
    else:
        raise AssertionError("重复删除应被拒绝")
    events = [value for value in session.added if isinstance(value, HoldingChange)]
    assert len(events) == 1


# 验证迁移链、MySQL 属性、日期回填和空关联转换均有静态约束。
def test_b1_migration_static_contract():
    from pathlib import Path

    path = Path(__file__).parents[2] / "alembic/versions/b1c2d3e4f5a6_add_holding_event_source_and_business_date.py"
    text = path.read_text(encoding="utf-8")
    assert 'down_revision: Union[str, None] = "a1b2c3d4e5f6"' in text
    assert text.count("existing_type=") >= 5
    assert "CURRENT_DATE" not in text
    assert "import_id = NULL WHERE import_id = 0" in text
    assert "idx_hc_holding_business_id" in text


# 验证文件新增和变更入口保留 file 来源、真实导入号和批次日期。
def test_file_merge_entry_writes_file_events():
    h = type("ParsedHolding", (), {
        "unique_key": "000103|平台A|账户A|交易A", "fund_code": "000103",
        "fund_name": "虚构基金", "share_type": "前收费", "management_company": None,
        "platform": "平台A", "fund_account": "账户A", "trade_account": "交易A",
        "shares": Decimal("5"), "share_date": date(2026, 9, 4),
        "nav": Decimal("2"), "nav_date": date(2026, 9, 4),
        "market_value": Decimal("10"), "currency": "人民币", "dividend_mode": None,
    })()
    fund = Fund(fund_code="000103", fund_name="虚构基金")

    class MergeSession:
        def __init__(self, values):
            self.values = iter(values)
            self.added = []

        def execute(self, _statement):
            return next(self.values)

        def add(self, value):
            self.added.append(value)

        def flush(self):
            for value in self.added:
                if getattr(value, "id", None) is None:
                    value.id = 1

    session = MergeSession([_ImportResult(None), _ImportResult(None), _RowsResult([])])
    _, _, _, changes = ImportService(session)._merge_holdings(
        [h], 77, date(2026, 9, 4)
    )
    assert changes[0].import_id == 77
    assert changes[0].source_type == "file"
    assert changes[0].business_date == date(2026, 9, 4)

    existing = _holding_for_entry(fund_code="000103", platform="平台A",
                                  fund_account="账户A", trade_account="交易A",
                                  shares=Decimal("4"), source_type="file",
                                  last_import_id=76)
    update_session = MergeSession([_ImportResult(existing), _ImportResult(fund), _RowsResult([])])
    _, _, _, updates = ImportService(update_session)._merge_holdings(
        [h], 78, date(2026, 9, 5)
    )
    assert updates[0].import_id == 78
    assert updates[0].business_date == date(2026, 9, 5)
    assert updates[0].shares_delta == Decimal("1")


# 验证日历历史状态按业务日期和事件 id 取同日最后事件。
def test_calendar_rebuild_uses_business_date_and_event_id_order():
    first = build_holding_change(
        holding_id=1, fund_code="000106", fund_name="虚构基金", platform="平台A",
        change_type="new", shares_before=Decimal("0"), shares_after=Decimal("5"),
        shares_delta=Decimal("5"), nav_at_change=Decimal("2"),
        mv_before=Decimal("0"), mv_after=Decimal("10"),
        business_date=date(2026, 9, 4), source_type="quick",
    )
    first.id = 1
    second = build_holding_change(
        holding_id=1, fund_code="000106", fund_name="虚构基金", platform="平台A",
        change_type="increase", shares_before=Decimal("5"), shares_after=Decimal("7"),
        shares_delta=Decimal("2"), nav_at_change=Decimal("2"),
        mv_before=Decimal("10"), mv_after=Decimal("14"),
        business_date=date(2026, 9, 4), source_type="manual",
    )
    second.id = 2
    holding = _holding_for_entry(id=1, fund_code="000106")
    shares = CalendarService(None)._get_effective_shares(
        date(2026, 9, 4), holding, {1: [first, second]}
    )
    assert shares == Decimal("7")


# 验证快照净资金流直接累计当日全部带符号事件。
def test_snapshot_net_inflow_uses_all_business_date_events():
    first = build_holding_change(
        holding_id=1, fund_code="000107", fund_name="虚构基金", platform="平台A",
        change_type="new", shares_before=Decimal("0"), shares_after=Decimal("5"),
        shares_delta=Decimal("5"), nav_at_change=Decimal("2"),
        mv_before=Decimal("0"), mv_after=Decimal("10"),
        business_date=date(2026, 9, 4), source_type="quick",
    )
    second = build_holding_change(
        holding_id=1, fund_code="000107", fund_name="虚构基金", platform="平台A",
        change_type="decrease", shares_before=Decimal("5"), shares_after=Decimal("3"),
        shares_delta=Decimal("-2"), nav_at_change=Decimal("2"),
        mv_before=Decimal("10"), mv_after=Decimal("6"),
        business_date=date(2026, 9, 4), source_type="manual",
    )

    class Session:
        def execute(self, _statement):
            return type("Rows", (), {"scalars": lambda self: type("Scalar", (), {"all": lambda self: [first, second]})()})()

    assert SnapshotService(Session())._calculate_net_inflow(date(2026, 9, 4)) == Decimal("6")


# 验证真实手工入口在事件写入失败时回滚持仓变更。
def test_manual_entry_rolls_back_when_event_write_fails():
    session = _EntrySession([None], fail_event=True)
    try:
        HoldingService(session).create_holding(HoldingCreate(
            fund_code="000104", fund_name="虚构基金", platform="平台A",
            shares=Decimal("1"), share_date=date(2026, 9, 4),
        ))
    except RuntimeError as exc:
        assert "事件写入失败" in str(exc)
    else:
        raise AssertionError("应在事件写入失败时抛出异常")
    assert session.rollbacks == 1
