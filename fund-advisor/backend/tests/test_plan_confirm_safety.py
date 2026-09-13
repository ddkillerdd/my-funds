"""投资计划确认的虚拟账本隔离、事务和并发意图合成测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.models.fund_candidate import FundCandidate
from backend.models.plan_holding import PlanHolding
from backend.models.plan_tranche import PlanTranche
from backend.models.portfolio_plan import PortfolioPlan
from backend.services.plan import PlanService


class _FakeResult:
    """提供计划服务所需的最小 SQLAlchemy 结果接口。"""

    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = list(rows or [])

    def scalar_one_or_none(self):
        """返回单行或空值。"""
        return self._scalar

    def scalars(self):
        """返回可继续调用 all 的结果对象。"""
        return self

    def all(self):
        """返回多行结果。"""
        return self._rows


class _FakeTranche:
    """内存中的虚构待执行批次。"""

    def __init__(self, amount=100):
        self.id = 10
        self.plan_id = 1
        self.tranche_no = 1
        self.amount = Decimal(str(amount))
        self.status = "pending"
        self.executed_at = None

    def concise(self):
        """返回确认响应所需的批次摘要。"""
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "tranche_no": self.tranche_no,
            "amount": float(self.amount),
            "status": self.status,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


class _FakeSession:
    """不连接数据库、记录事务和行锁意图的虚构 Session。"""

    def __init__(self, plan, tranches):
        self.plan = plan
        self.tranches = tranches
        self.initial_remaining = plan.remaining
        self.plan_holdings = {}
        self.commit_count = 0
        self.rollback_count = 0
        self.locked_entities = []

    def execute(self, statement):
        """按查询实体返回内存对象并记录 FOR UPDATE 意图。"""
        entity = statement.column_descriptions[0].get("entity")
        lock_intended = getattr(statement, "_for_update_arg", None) is not None
        self.locked_entities.append((entity, lock_intended))

        if entity is PortfolioPlan:
            return _FakeResult(scalar=self.plan)
        if entity is PlanTranche:
            pending = [tr for tr in self.tranches if tr.status == "pending"]
            return _FakeResult(rows=pending)
        if entity is PlanHolding:
            code = None
            for criterion in statement._where_criteria:
                left = getattr(criterion, "left", None)
                if getattr(left, "name", None) == "fund_code":
                    code = getattr(getattr(criterion, "right", None), "value", None)
                    break
            return _FakeResult(scalar=self.plan_holdings.get(code))
        if entity is FundCandidate:
            return _FakeResult(scalar=None)
        return _FakeResult()

    def add(self, obj):
        """记录新建的虚拟计划持仓。"""
        if isinstance(obj, PlanHolding):
            self.plan_holdings[obj.fund_code] = obj

    def commit(self):
        """记录唯一一次成功提交。"""
        self.commit_count += 1

    def rollback(self):
        """回滚虚构事务中的计划域变更。"""
        self.rollback_count += 1
        if self.commit_count:
            return
        self.plan.used_amount = Decimal("0")
        self.plan.remaining = self.initial_remaining
        self.plan.status = "draft"
        self.plan.approved_at = None
        self.plan_holdings.clear()
        for tranche in self.tranches:
            tranche.amount = Decimal("100")
            tranche.status = "pending"
            tranche.executed_at = None


def _make_fixture(nav_map, remaining=1000, amount=100):
    """创建计划、批次和虚构 Session。"""
    plan = SimpleNamespace(
        id=1,
        total_budget=Decimal("1000"),
        used_amount=Decimal("0"),
        remaining=Decimal(str(remaining)),
        status="draft",
        approved_at=None,
        target_allocation={"A": 60.0, "B": 40.0},
    )
    tranche = _FakeTranche(amount=amount)
    db = _FakeSession(plan, [tranche])
    service = PlanService(db)
    service._latest_nav = lambda code: nav_map.get(code)
    global_calls = []
    service._sync_global_holding = (
        lambda *args: global_calls.append(args)
    )
    return service, db, plan, tranche, global_calls


def test_fixture_a_missing_nav_is_atomic_and_plan_only():
    """夹具A：缺B净值时整批不写入、不支出、不提交。"""
    service, db, plan, tranche, global_calls = _make_fixture(
        {"A": Decimal("2"), "B": None}
    )

    with pytest.raises(ValueError, match="B"):
        service.confirm_entry(plan.id, execute_tranches=1)

    assert plan.used_amount == Decimal("0")
    assert plan.remaining == Decimal("1000")
    assert tranche.status == "pending"
    assert tranche.amount == Decimal("100")
    assert tranche.executed_at is None
    assert db.plan_holdings == {}
    assert global_calls == []
    assert db.commit_count == 0
    assert db.rollback_count == 1


def test_fixture_b_success_only_updates_virtual_plan_domain():
    """夹具B：2/4净值下只写计划金额60/40和份额30/10。"""
    service, db, plan, tranche, global_calls = _make_fixture(
        {"A": Decimal("2"), "B": Decimal("4")}
    )

    result = service.confirm_entry(plan.id, execute_tranches=1)

    assert db.plan_holdings["A"].total_cost == Decimal("60.0")
    assert db.plan_holdings["A"].total_units == Decimal("30")
    assert db.plan_holdings["B"].total_cost == Decimal("40.0")
    assert db.plan_holdings["B"].total_units == Decimal("10")
    assert plan.used_amount == Decimal("100")
    assert plan.remaining == Decimal("900")
    assert tranche.status == "executed"
    assert tranche.amount == Decimal("100")
    assert plan.status == "active"
    assert db.commit_count == 1
    assert global_calls == []
    assert result["ledger_scope"] == "plan_only"
    assert result["global_holdings_updated"] is False
    assert result["message"]
    assert sum(
        db.plan_holdings[code].total_cost for code in ("A", "B")
    ) == Decimal("100")


def test_fixture_c_insufficient_budget_is_not_truncated():
    """夹具C：资金不足时整批拒绝，不静默截断为剩余预算。"""
    service, db, plan, tranche, global_calls = _make_fixture(
        {"A": Decimal("2"), "B": Decimal("4")}, remaining=80, amount=100
    )

    with pytest.raises(ValueError, match="不足"):
        service.confirm_entry(plan.id, execute_tranches=1)

    assert plan.used_amount == Decimal("0")
    assert plan.remaining == Decimal("80")
    assert tranche.status == "pending"
    assert tranche.amount == Decimal("100")
    assert db.plan_holdings == {}
    assert global_calls == []
    assert db.commit_count == 0
    assert db.rollback_count == 1


def test_fixture_d_repeat_confirmation_is_idempotent_and_locked():
    """夹具D：重复确认不重复累计，计划和批次查询均有锁意图。"""
    service, db, plan, tranche, global_calls = _make_fixture(
        {"A": Decimal("2"), "B": Decimal("4")}
    )

    service.confirm_entry(plan.id, execute_tranches=1)
    first_costs = {
        code: db.plan_holdings[code].total_cost for code in ("A", "B")
    }

    with pytest.raises(ValueError, match="没有待执行批次"):
        service.confirm_entry(plan.id, execute_tranches=1)

    assert plan.used_amount == Decimal("100")
    assert plan.remaining == Decimal("900")
    assert {
        code: db.plan_holdings[code].total_cost for code in ("A", "B")
    } == first_costs
    assert db.commit_count == 1
    assert global_calls == []
    assert any(
        entity is PortfolioPlan and locked
        for entity, locked in db.locked_entities
    )
    assert any(
        entity is PlanTranche and locked
        for entity, locked in db.locked_entities
    )


def test_fixture_e_mid_batch_error_rolls_back_and_does_not_commit():
    """夹具E：第二只基金异常时回滚整批且异常继续上抛。"""
    service, db, plan, tranche, global_calls = _make_fixture(
        {"A": Decimal("2"), "B": Decimal("4")}
    )
    original_upsert = service._upsert_plan_holding

    def fail_on_b(plan_id, code, *args):
        """在B的虚拟计划持仓写入处注入异常。"""
        if code == "B":
            raise RuntimeError("合成中途异常")
        return original_upsert(plan_id, code, *args)

    service._upsert_plan_holding = fail_on_b

    with pytest.raises(RuntimeError, match="中途异常"):
        service.confirm_entry(plan.id, execute_tranches=1)

    assert db.commit_count == 0
    assert db.rollback_count == 1
    assert plan.used_amount == Decimal("0")
    assert plan.remaining == Decimal("1000")
    assert tranche.status == "pending"
    assert db.plan_holdings == {}
    assert global_calls == []
