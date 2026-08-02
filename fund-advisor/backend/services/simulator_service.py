"""SimulatorService — 组合策略回测"盈利能力分析+优化建议"(RFC-016).

职责:
  1. 桥接 fund-analyzer 的 Simulator(纯引擎, 零 LLM)
  2. 支持用户自定义基金 + 初始成本(金额)
  3. 把引擎输出的每窗口每日净值, 加工成"每日盈亏曲线"(供前端直观展示)
  4. 以"盈利"为核心: 多窗口超额判定盈利能力 -> 生成可执行的优化建议

设计原则:
  - 引擎只做"回放", 本服务做"盈利解读 + 建议"(与 AdvisorService 对引擎的解读角色一致)
  - 判定全部基于超额收益(excess_return)与回撤, 不靠主观
"""

import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---- 注入 fund-analyzer 引擎(与现有 backend/services 一致的桥接方式) ----
_ENGINE_PATH = "/root/.openclaw/workspace/fund-analyzer"
if _ENGINE_PATH not in sys.path:
    sys.path.insert(0, _ENGINE_PATH)

from engine.simulator import Simulator  # noqa: E402
from engine.models import NavPoint  # noqa: E402

# 可回测的最低历史天数(需覆盖 warmup + 最短窗口, 约 1 年)
MIN_BACKTEST_DAYS = 210


class SimulatorService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------
    #  数据准备: 用户指定基金 -> nav_history + 各基金信息
    # ---------------------------------------------------------------
    def _fund_info_map(self) -> Dict[str, dict]:
        """全部基金元信息(code -> {code,name,latest_nav,nav_days})。"""
        from backend.models.fund import Fund
        from backend.models.nav_history import FundNavHistory
        from sqlalchemy import func
        rows = self.db.execute(
            select(Fund.fund_code, Fund.fund_name, Fund.latest_nav)
        ).all()
        info = {r[0]: {"code": r[0], "name": r[1], "latest_nav": r[2]} for r in rows}

        # 统计历史天数
        cnt_rows = self.db.execute(
            select(FundNavHistory.fund_code, func.count(FundNavHistory.fund_code))
            .group_by(FundNavHistory.fund_code)
        ).all()
        for code, cnt in cnt_rows:
            if code in info:
                info[code]["nav_days"] = cnt
            else:
                info[code] = {"code": code, "name": code, "latest_nav": None, "nav_days": cnt}
        return info

    def list_fund_options(self) -> List[dict]:
        """前端下拉可选基金(含回测可行性标记)。"""
        info = self._fund_info_map()
        out = []
        for code, d in sorted(info.items()):
            out.append({
                "fund_code": code,
                "fund_name": d.get("name") or code,
                "latest_nav": d.get("latest_nav"),
                "nav_days": d.get("nav_days", 0),
                "can_backtest": d.get("nav_days", 0) >= MIN_BACKTEST_DAYS,
            })
        return out

    def _get_nav_history(self, fund_code: str) -> List[NavPoint]:
        """取某基金完整净值历史(时间升序)-> NavPoint 列表。"""
        from backend.models.nav_history import FundNavHistory
        records = self.db.execute(
            select(FundNavHistory.nav_date, FundNavHistory.unit_nav)
            .where(FundNavHistory.fund_code == fund_code)
            .order_by(FundNavHistory.nav_date.asc())
        ).all()
        navs = [NavPoint(date=str(r[0]), nav=float(r[1])) for r in records if r[1] is not None]
        return navs

    # ---------------------------------------------------------------
    #  主入口
    # ---------------------------------------------------------------
    def run(
        self,
        funds_in: List[dict],
        initial_amount: Optional[float] = None,
        windows: Optional[List[int]] = None,
        warmup: int = 252,
        target_vol: float = 0.15,
        friction_band_pp: float = 5.0,
    ) -> dict:
        """执行回测并返回完整响应(窗口/每日盈亏/盈利判定/优化建议)。

        funds_in: [{"fund_code","fund_name","amount"}, ...]
        """
        info = self._fund_info_map()
        funds_used = []

        # 1. 组装引擎输入: 每只基金 code/name/nav_history + 初始金额
        engine_funds = []
        total_amount = 0.0
        initial_weights = {}
        for fin in funds_in:
            code = fin["fund_code"]
            amount = float(fin.get("amount") or 0)
            name = fin.get("fund_name") or info.get(code, {}).get("name") or code
            navs = self._get_nav_history(code)
            if not navs:
                continue  # 无历史, 跳过
            engine_funds.append({"code": code, "name": name, "nav_history": navs})
            total_amount += amount
            funds_used.append({
                "fund_code": code, "fund_name": name,
                "amount": amount,
                "history_days": len(navs),
            })

        # 默认: 用当前持仓组合(等权, 总成本=10000 便于看百分比)
        if not engine_funds:
            engine_funds, funds_used, total_amount = self._default_portfolio(info)

        # 初始总资金
        if initial_amount and initial_amount > 0:
            total_amount = float(initial_amount)
        if total_amount <= 0:
            total_amount = sum(f["amount"] for f in funds_used) or 10000.0

        for u in funds_used:
            if u["amount"] and u["amount"] > 0:
                initial_weights[u["fund_code"]] = round(u["amount"] / total_amount, 4)

        # 2. 跑引擎
        sim = Simulator(
            initial_amount=total_amount,
            windows=windows,
            warmup=min(warmup, 252),
            target_vol=target_vol,
            friction_band_pp=friction_band_pp,
        )
        report = sim.simulate(engine_funds)

        # 3. 加工为响应
        windows_out = {}
        for wd_str, win in report.windows.items():
            windows_out[str(wd_str)] = self._window_to_out(win, total_amount)

        summary = self._build_summary(report, windows_out)
        advice = self._build_advice(report, windows_out, funds_used)

        return {
            "generated_at": report.generated_at,
            "duration_seconds": report.duration_seconds,
            "initial_amount": report.initial_amount,
            "initial_weights": initial_weights,
            "target_vol": report.target_vol,
            "warmup": report.warmup,
            "windows": windows_out,
            "summary": summary,
            "advice": advice,
            "funds_used": funds_used,
        }

    # ---------------------------------------------------------------
    #  加工单窗口 -> 含每日盈亏
    # ---------------------------------------------------------------
    def _window_to_out(self, win, initial_amount: float) -> dict:
        daily = []
        prev_value = None
        for snap in win.daily:
            total = round(snap.total_value, 2)
            if prev_value is None:
                day_pnl = 0.0
            else:
                day_pnl = round(total - prev_value, 2)
            cum_pnl = round(total - initial_amount, 2)
            cum_ret = round((total / initial_amount - 1) * 100, 2) if initial_amount else 0.0
            prev_value = total
            daily.append({
                "date": snap.date,
                "total_value": total,
                "holdings_value": round(snap.holdings_value, 2),
                "cash": round(snap.cash, 2),
                "daily_pnl": day_pnl,
                "cumulative_pnl": cum_pnl,
                "cumulative_return_pct": cum_ret,
                "actions": snap.actions,
                "target_weights": snap.target_weights,
            })

        return {
            "window_days": win.window_days,
            "start_date": win.start_date,
            "end_date": win.end_date,
            "initial_amount": win.initial_amount,
            "final_value": win.final_value,
            "strategy_return_pct": win.strategy_return_pct,
            "buy_hold_return_pct": win.buy_hold_return_pct,
            "excess_return_pct": win.excess_return_pct,
            "strategy_max_drawdown_pct": win.strategy_max_drawdown_pct,
            "buy_hold_max_drawdown_pct": win.buy_hold_max_drawdown_pct,
            "is_profitable": win.strategy_return_pct > 0,
            "beats_buy_hold": win.excess_return_pct > 0,
            "per_fund": win.per_fund,
            "final_weights": win.final_weights,
            "daily": daily,
        }

    # ---------------------------------------------------------------
    #  盈利判定(以盈利为核心)
    # ---------------------------------------------------------------
    def _build_summary(self, report, windows_out: Dict[str, dict]) -> dict:
        wins = list(windows_out.values())
        if not wins:
            return {
                "avg_excess_pct": 0, "best_excess_pct": 0, "worst_excess_pct": 0,
                "profitable_windows": 0, "total_windows": 0,
                "overall_profitable": False, "profit_confidence": "low",
                "verdict": "无足够历史数据, 无法回测",
            }

        prof = sum(1 for w in wins if w["is_profitable"])
        beats = sum(1 for w in wins if w["beats_buy_hold"])
        avg_excess = round(sum(w["excess_return_pct"] for w in wins) / len(wins), 2)
        best = round(max(w["excess_return_pct"] for w in wins), 2)
        worst = round(min(w["excess_return_pct"] for w in wins), 2)

        # 盈利判定: 多数窗口正超额 且 平均超额 > 0
        overall_profitable = beats >= len(wins) * 0.6 and avg_excess > 0
        if overall_profitable and avg_excess >= 3:
            confidence = "high"
        elif overall_profitable:
            confidence = "medium"
        elif avg_excess > 0:
            confidence = "medium"
        else:
            confidence = "low"

        if overall_profitable:
            verdict = (f"整体具有盈利能力: 策略平均超额 {avg_excess:+.2f}%, "
                       f"{beats}/{len(wins)} 个窗口跑赢死拿。")
        elif avg_excess > 0:
            verdict = (f"弱盈利: 平均超额 {avg_excess:+.2f}% 但仅 {beats}/{len(wins)} "
                       f"窗口跑赢, 稳定性不足, 建议收紧风险参数。")
        else:
            verdict = (f"暂未跑出稳定盈利: 平均超额 {avg_excess:+.2f}%, "
                       f"策略不如死拿, 建议下调 target_vol 减少追涨杀跌或检查信号方向。")

        return {
            "avg_excess_pct": avg_excess,
            "best_excess_pct": best,
            "worst_excess_pct": worst,
            "profitable_windows": prof,
            "total_windows": len(wins),
            "overall_profitable": overall_profitable,
            "profit_confidence": confidence,
            "verdict": verdict,
        }

    # ---------------------------------------------------------------
    #  优化建议(以盈利为核心, 基于数据可执行)
    # ---------------------------------------------------------------
    def _build_advice(self, report, windows_out: Dict[str, dict], funds_used: List[dict]) -> List[dict]:
        advice: List[dict] = []
        wins = list(windows_out.values())
        if not wins:
            return advice

        # 1. 长期窗口(365)超额是否成立 -> 信号方向有效性
        long_win = windows_out.get("365")
        if long_win:
            if long_win["excess_return_pct"] > 0:
                advice.append({
                    "level": "success",
                    "target": "全年窗口(365天)",
                    "message": (f"长期策略超额 {long_win['excess_return_pct']:+.2f}%, "
                                f"买/卖信号方向大致成立, 可维持当前决策参数。"),
                    "action": "维持策略, 可小幅提高仓位利用率",
                })
            else:
                advice.append({
                    "level": "danger",
                    "target": "全年窗口(365天)",
                    "message": (f"长期策略超额 {long_win['excess_return_pct']:+.2f}%, "
                                f"动态调仓不及死拿, 信号在高波动市场易追涨杀跌。"),
                    "action": "下调 target_vol(如 0.15->0.10)并加大 friction_band(5->8)减少换手",
                })

        # 2. 回撤过大 -> 风险控制
        risky = [w for w in wins if w["strategy_max_drawdown_pct"] > 15 and w["window_days"] >= 90]
        if risky:
            rr = risky[0]
            advice.append({
                "level": "warning",
                "target": f"{rr['window_days']}天窗口",
                "message": (f"策略最大回撤 {rr['strategy_max_drawdown_pct']:.1f}% 偏大, "
                            f"虽收益可能为正, 但持有体验差、回撤中易恐慌抛售。"),
                "action": "收紧 target_vol 或为高波动基金设个股仓位上限(DHARD_STOP)",
            })

        # 3. 单基金贡献: 找拖后腿的基金
        worst_code = None
        worst_gap = -999
        for w in wins:
            for code, fd in (w.get("per_fund") or {}).items():
                # per_fund 含 final_weight_pct; 用超额辅助判断
                pass
        # per_fund 数据有限, 改用: 长期窗口期末权重 vs 初始等权, 识别过度集中
        long_win2 = windows_out.get("365") or list(windows_out.values())[0]
        fw = long_win2.get("final_weights") or {}
        if fw and funds_used:
            for code, wgt in fw.items():
                amount = next((f["amount"] for f in funds_used if f["fund_code"] == code), None)
                if amount and wgt * long_win2["initial_amount"] > amount:
                    advice.append({
                        "level": "info",
                        "target": f"基金 {code}",
                        "message": (f"策略期末将其仓位加至 {wgt*100:.0f}%(高于初始占比), "
                                    f"说明信号持续看好, 已加仓。"),
                        "action": "若该基金近一年超额为正则维持; 否则设定单基上限防过度集中",
                    })

        # 4. 组合总体
        s = self._summary_lite(advice, wins)
        if wins and s["max_dd"] < 10:
            advice.insert(0, {
                "level": "success",
                "target": "组合整体",
                "message": f"策略最大回撤仅 {s['max_dd']:.1f}%, 风险控制良好。",
                "action": "可适当提升 target_vol 释放收益空间",
            })

        if not any(a["level"] == "danger" for a in advice) and wins:
            avg = round(sum(w["excess_return_pct"] for w in wins) / len(wins), 2)
            if avg > 0 and len(advice) == 0:
                advice.append({
                    "level": "success", "target": "组合整体",
                    "message": "各窗口均跑出正超额, 当前策略配置健康。",
                    "action": "继续观察, 可在回撤加大时再收紧风险",
                })

        return advice

    def _summary_lite(self, advice, wins):
        return {
            "max_dd": max((w["strategy_max_drawdown_pct"] for w in wins), default=0),
        }

    # ---------------------------------------------------------------
    #  默认组合(未指定时)
    # ---------------------------------------------------------------
    def _default_portfolio(self, info: Dict[str, dict]):
        """用当前持仓的真实基金(等权), 返回 (engine_funds, funds_used, total)。"""
        from backend.models.holding import FundHolding
        held = self.db.execute(
            select(FundHolding.fund_code).where(FundHolding.status == 1)
        ).scalars().all()
        codes = list(dict.fromkeys(held))  # 去重保序
        if not codes:
            # 兜底: 全部有足够历史的基金
            codes = [c for c, d in info.items() if d.get("nav_days", 0) >= MIN_BACKTEST_DAYS]

        engine_funds = []
        funds_used = []
        total = 0.0
        for code in codes:
            navs = self._get_nav_history(code)
            if not navs:
                continue
            name = info.get(code, {}).get("name") or code
            amt = 10000.0 / len(codes) if codes else 10000.0
            engine_funds.append({"code": code, "name": name, "nav_history": navs})
            funds_used.append({"fund_code": code, "fund_name": name, "amount": round(amt, 2),
                               "history_days": len(navs)})
            total += amt
        return engine_funds, funds_used, total
