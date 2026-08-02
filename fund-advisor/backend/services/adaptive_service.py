"""
adaptive_service.py — 自适应参数优化桥接服务 (RFC-017 · 甲方案·半自动模式 X)

职责
----
1. 桥接 fund-analyzer 的 WFA 引擎(adaptive_optimizer) + 分类(strategy_config).
2. WFA 计算较慢(数十秒~分钟), 用 asyncio.create_task 做后台任务, 前端轮询状态.
3. 产出 AdaptiveProposal 落库(status=pending), 用户确认后才 approved.
4. 报告侧通过 get_active_config(fund_code) 读取该基金生效参数:
   - 有 approved override → 用之
   - 无 → 保守默认(按风险分类)

安全设计
--------
- 只有 status=approved 的 proposal 才能写入 strategy_override.
- 未确认(pending)/否决(rejected) 一律不影响实盘.
- 每个 risk_class 只能有一个生效 override(unique 约束).

用法(api 层)
------------
svc = AdaptiveService(db)
task_id = svc.submit_optimize()          # 异步发起, 立即返回
status = svc.task_status(task_id)        # 轮询
proposals = svc.list_proposals()         # 列推荐
svc.approve(proposal_id, note)           # 采纳 -> 写入 override
svc.reject(proposal_id, note)            # 否决
cfg = svc.get_active_config("000311")    # 报告侧读取
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

# ---- 注入 fund-analyzer 引擎(与 backend/services 一致的桥接方式) ----
_ENGINE_PATH = "/root/.openclaw/workspace/fund-analyzer"
if _ENGINE_PATH not in sys.path:
    sys.path.insert(0, _ENGINE_PATH)

from engine.strategy_config import (  # noqa: E402
    FundStrategyConfig, class_default, classify_fund,
)
from engine.adaptive_optimizer import optimize_fund_class  # noqa: E402

from backend.models.adaptive_proposal import AdaptiveProposal  # noqa: E402
from backend.models.strategy_override import StrategyOverride  # noqa: E402

logger = logging.getLogger("fund.adaptive")

# 滚动窗口长度(最近 N 个交易日参与 WFA)—— 呼应"WFA 滚动取最近 3~5 年",
# 但这里给默认 ~2.5 年(约 600 交易日)保证速度; 足够数据时前端可传更长。
DEFAULT_LOOKBACK_DAYS = 600

# 后台任务注册表(内存态; 重启即清, 可接受——任务结果会落库)
_TASKS: Dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


def _new_task_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _set_task(task_id: str, **patch):
    with _TASKS_LOCK:
        _TASKS.setdefault(task_id, {"task_id": task_id, "status": "running", "error": None})
        _TASKS[task_id].update(patch)


class AdaptiveService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------
    # 异步任务
    # ---------------------------------------------------------------
    def submit_optimize(self, fund_codes: Optional[List[str]] = None,
                        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                        tv_grid: Optional[List[float]] = None,
                        fr_grid: Optional[List[int]] = None) -> dict:
        """
        异步发起一次 WFA 自适应优化(对参与基金自动分类, 各类分别跑)。
        用后台线程执行(WFA 是 CPU 密集, 不依赖事件循环), 立即返回 task_id。
        后台线程使用独立数据库 Session, 避免与请求线程共享。
        """
        task_id = _new_task_id()
        _set_task(task_id, status="pending", progress="排队中")

        def _worker():
            from backend.database import SessionLocal
            with SessionLocal() as db:
                try:
                    svc = AdaptiveService(db)
                    svc._run_optimize_sync(task_id, fund_codes, lookback_days,
                                           tv_grid, fr_grid)
                except Exception:  # noqa: BLE001
                    logger.exception("adaptive worker failed")
                    _set_task(task_id, status="error", error="内部错误")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return {"task_id": task_id, "status": "running"}

    def _run_optimize_sync(self, task_id, fund_codes, lookback_days, tv_grid, fr_grid):
        _set_task(task_id, status="running", progress="加载基金历史...")
        try:
            funds_data = self._load_funds(fund_codes, lookback_days)
            if not funds_data:
                _set_task(task_id, status="error", error="没有可用基金数据")
                return

            # 自动分类(按风险特征), 各类分别优化
            classes = {}
            for f in funds_data:
                cls = classify_fund(f["nav_history"])
                classes.setdefault(cls, []).append(f)

            total = len(classes)
            created = 0
            for i, (cls, funds) in enumerate(classes.items(), 1):
                _set_task(task_id, progress=f"优化 {cls} 波动类({i}/{total})...")
                prop = optimize_fund_class(funds, risk_class=cls,
                                           tv_grid=tv_grid, fr_grid=fr_grid,
                                           progress_cb=lambda m: _set_task(task_id, progress=m))
                self._persist_proposal(prop, cls)
                created += 1

            _set_task(task_id, status="done", progress="完成",
                      result={"proposals_created": created})
        except Exception as e:  # noqa: BLE001
            logger.exception("adaptive optimize failed")
            _set_task(task_id, status="error", error=str(e))

    def task_status(self, task_id: str) -> Optional[dict]:
        return dict(_TASKS.get(task_id, {}))

    # ---------------------------------------------------------------
    # 数据加载
    # ---------------------------------------------------------------
    def _load_funds(self, fund_codes, lookback_days) -> List[dict]:
        codes = fund_codes or self._default_fund_codes()
        from backend.services.simulator_service import SimulatorService
        svc = SimulatorService(self.db)
        out = []
        for c in codes:
            navs = svc._get_nav_history(c)
            if navs:
                navs = navs[-lookback_days:] if lookback_days else navs
                out.append({"code": c, "name": c, "nav_history": navs})
        return out

    def _default_fund_codes(self) -> List[str]:
        from backend.models.fund import Fund
        rows = self.db.execute(select(Fund.fund_code)).all()
        codes = [r[0] for r in rows if r[0]]
        return codes or []

    # ---------------------------------------------------------------
    # 持久化
    # ---------------------------------------------------------------
    def _persist_proposal(self, prop, risk_class):
        row = AdaptiveProposal(
            risk_class=risk_class,
            fund_codes=",".join(prop.fund_codes),
            target_vol=round(prop.best_target_vol, 4),
            friction_band_pp=round(prop.best_friction_band_pp, 4),
            default_target_vol=round(prop.default_target_vol, 4),
            default_friction_band_pp=round(prop.default_friction_band_pp, 4),
            avg_test_excess_pct=round(prop.avg_test_excess_pct, 4),
            best_max_drawdown=round(prop.best_max_drawdown, 4),
            best_wfe=round(prop.best_wfe, 4),
            train_days=prop.train_days,
            test_days=prop.test_days,
            data_start=prop.data_start,
            data_end=prop.data_end,
            passed=1 if prop.passed else 0,
            reasons="\n".join(prop.reasons),
            notes="\n".join(prop.notes),
            status="pending",
        )
        self.db.add(row)
        self.db.commit()
        logger.info("adaptive proposal #%s(%s) 已落库, passed=%s",
                    row.id, risk_class, prop.passed)

    # ---------------------------------------------------------------
    # 查询 / 采纳 / 否决
    # ---------------------------------------------------------------
    def list_proposals(self, status: Optional[str] = None,
                       limit: int = 50) -> List[dict]:
        stmt = select(AdaptiveProposal).order_by(
            desc(AdaptiveProposal.id)).limit(limit)
        if status:
            stmt = stmt.where(AdaptiveProposal.status == status)
        rows = self.db.execute(stmt).scalars().all()
        return [r.concise() for r in rows]

    def approve(self, proposal_id, note: str = "") -> dict:
        row = self.db.execute(
            select(AdaptiveProposal).where(AdaptiveProposal.id == proposal_id)
        ).scalar_one_or_none()
        if not row:
            raise ValueError(f"proposal #{proposal_id} 不存在")
        if not row.passed:
            raise ValueError("该推荐未通过稳健性校验, 不可采纳")
        row.status = "approved"
        row.decided_at = datetime.utcnow()
        row.decided_note = note
        # 写入生效 override(唯一 per class)
        ov = self.db.execute(
            select(StrategyOverride).where(
                StrategyOverride.risk_class == row.risk_class)
        ).scalar_one_or_none()
        if ov is None:
            ov = StrategyOverride(risk_class=row.risk_class)
            self.db.add(ov)
        ov.target_vol = row.target_vol
        ov.friction_band_pp = row.friction_band_pp
        ov.source = "approved"
        ov.proposal_id = row.id
        ov.note = note or f"采纳自 proposal#{row.id}"
        ov.updated_at = datetime.utcnow()
        self.db.commit()
        logger.info("proposal #%s approved -> override(%s) tv=%s", proposal_id,
                    row.risk_class, row.target_vol)
        return {"status": "approved", "risk_class": row.risk_class}

    def reject(self, proposal_id, note: str = "") -> dict:
        row = self.db.execute(
            select(AdaptiveProposal).where(AdaptiveProposal.id == proposal_id)
        ).scalar_one_or_none()
        if not row:
            raise ValueError(f"proposal #{proposal_id} 不存在")
        row.status = "rejected"
        row.decided_at = datetime.utcnow()
        row.decided_note = note
        self.db.commit()
        logger.info("proposal #%s rejected", proposal_id)
        return {"status": "rejected"}

    def active_overrides(self) -> List[dict]:
        rows = self.db.execute(select(StrategyOverride)).scalars().all()
        return [r.to_dict() for r in rows]

    # ---------------------------------------------------------------
    # 报告侧读取生效参数
    # ---------------------------------------------------------------
    def get_active_config(self, fund_code: str = "",
                          risk_class: Optional[str] = None) -> FundStrategyConfig:
        """
        返回某基金(或其风险类别)当前应生效的策略参数。
        报告侧(analyzer 调用方)用它覆盖 decision 默认。

        优先级: approved override > 该类别保守默认。
        fund_code 可选(用于自动归类, 若调用方已知 risk_class 可不传)。
        """
        cls = risk_class
        if cls is None:
            try:
                from backend.services.simulator_service import SimulatorService
                navs = SimulatorService(self.db)._get_nav_history(fund_code)
                cls = classify_fund(navs) if navs else "medium"
            except Exception:  # noqa: BLE001
                cls = "medium"
        if cls not in ("low", "medium", "high"):
            cls = "medium"

        ov = self.db.execute(
            select(StrategyOverride).where(StrategyOverride.risk_class == cls)
        ).scalar_one_or_none()
        if ov is not None:
            return FundStrategyConfig(
                target_vol=float(ov.target_vol),
                friction_band_pp=float(ov.friction_band_pp),
                risk_class=cls,
                source="approved",
                proposal_id=ov.proposal_id,
                note=ov.note or f"approved override({cls})",
            )
        return class_default(cls)

    def reset_override(self, risk_class: str) -> dict:
        """撤销某类的生效参数, 回退保守默认。"""
        ov = self.db.execute(
            select(StrategyOverride).where(StrategyOverride.risk_class == risk_class)
        ).scalar_one_or_none()
        if ov:
            self.db.delete(ov)
            self.db.commit()
        return {"status": "reset", "risk_class": risk_class}
