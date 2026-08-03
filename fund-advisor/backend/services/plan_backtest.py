"""PlanBacktestService - 回测验证 (RFC-018 ④).

把 AI荐基/配比出的方案用历史数据回测验证。
- 复用 SimulatorService.run(组合策略回测, 多窗口) + 后续新增指标
- 新增: max_drawdown_recovery_days(最大回撤修复时长) + win_rate(盈利概率)
- 异步后台执行 + 前端轮询(性能, 秒~分钟级)
"""

import logging
import threading
import uuid
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.services.simulator_service import SimulatorService

logger = logging.getLogger(__name__)

# 后台任务注册表(进程内存, 与 adaptive_service 同思路)
_TASKS: Dict[str, dict] = {}


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def _set_task(task_id: str, **patch) -> None:
    _TASKS.setdefault(task_id, {"task_id": task_id, "status": "running", "error": None})
    _TASKS[task_id].update(patch)


class PlanBacktestService:
    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────
    #  提交异步回测
    # ─────────────────────────────────────────
    def submit_backtest(
        self,
        funds: List[dict],            # [{"fund_code","fund_name","amount"}]
        windows: Optional[List[int]] = None,
        target_vol: float = 0.15,
        friction_band_pp: float = 5.0,
    ) -> dict:
        if not funds:
            raise ValueError("funds 不能为空")
        task_id = _new_task_id()
        _set_task(task_id, status="pending", progress="排队中")
        funds_json = list(funds)
        windows_p = list(windows) if windows else None

        def _worker():
            try:
                _set_task(task_id, status="running", progress="回测中...")
                svc = PlanBacktestService(self._new_db_session())
                result = svc.run_backtest(
                    funds_json, windows=windows_p,
                    target_vol=target_vol, friction_band_pp=friction_band_pp,
                )
                _set_task(task_id, status="done", progress="完成", result=result)
            except Exception as e:  # noqa: BLE001
                logger.exception("plan backtest failed")
                _set_task(task_id, status="error", error=str(e)[:300])

        threading.Thread(target=_worker, daemon=True).start()
        return {"task_id": task_id, "status": "running"}

    def _new_db_session(self):
        from backend.database import SessionLocal
        return SessionLocal()

    # ─────────────────────────────────────────
    #  主回测(同步, 供后台线程调用)
    # ─────────────────────────────────────────
    def run_backtest(
        self,
        funds: List[dict],
        windows: Optional[List[int]] = None,
        target_vol: float = 0.15,
        friction_band_pp: float = 5.0,
    ) -> dict:
        if not windows:
            windows = [30, 90, 365]
        data = SimulatorService(self.db).run(
            funds_in=funds,
            windows=windows,
            target_vol=target_vol,
            friction_band_pp=friction_band_pp,
        )
        # 为每个窗口追加 回撤修复时长 + 盈利概率
        for wd_str, win in data.get("windows", {}).items():
            extra = self._extra_metrics(win.get("daily", []), win.get("initial_amount"))
            win["max_drawdown_recovery_days"] = extra["recovery_days"]
            win["recovery_status"] = extra["recovery_status"]
            win["win_rate_pct"] = extra["win_rate"]
        return data

    # ─────────────────────────────────────────
    #  新增指标(纯 daily 序列, 不改引擎内核)
    # ─────────────────────────────────────────
    def _extra_metrics(self, daily: List[dict], initial_amount) -> dict:
        """从每日序列算: 最大回撤修复时长 + 盈利概率。"""
        if not daily:
            return {"recovery_days": None, "recovery_status": "no_data", "win_rate": None}

        totals = [d.get("total_value") for d in daily]
        totals = [float(t) for t in totals if t is not None]

        # --- 盈利概率: 累计收益>0 的天数占比 ---
        win_days = sum(1 for t in totals if t > initial_amount)
        win_rate = round(win_days / len(totals) * 100, 1) if totals else None

        # --- 最大回撤修复时长 ---
        # 找最大回撤(与引擎 max_drawdown 对应的那一段)
        peak = totals[0]
        peak_idx = 0
        max_dd = 0.0
        trough_idx = 0
        for i, t in enumerate(totals):
            if t > peak:
                peak = t
                peak_idx = i
            dd = (peak - t) / peak if peak else 0
            if dd > max_dd:
                max_dd = dd
                trough_idx = i
        # 该回撤对应峰值时刻
        # 从 trough_idx 前进, 找恢复到原峰值的时刻
        recovery_days = None
        recovery_status = "no_drawdown" if max_dd <= 1e-6 else "recovering"
        if max_dd > 1e-6:
            peak_at_trough = max(totals[: trough_idx + 1]) if trough_idx > 0 else totals[0]
            recovered = None
            for j in range(trough_idx + 1, len(totals)):
                if totals[j] >= peak_at_trough:
                    recovered = j
                    break
            if recovered is not None:
                recovery_days = recovered - trough_idx
                recovery_status = "recovered"
            else:
                recovery_days = None
                recovery_status = "still_in_drawdown"
        return {
            "recovery_days": recovery_days,
            "recovery_status": recovery_status,
            "win_rate": win_rate,
        }

    # ─────────────────────────────────────────
    #  任务状态轮询
    # ─────────────────────────────────────────
    def task_status(self, task_id: str) -> Optional[dict]:
        return dict(_TASKS.get(task_id, {}))
