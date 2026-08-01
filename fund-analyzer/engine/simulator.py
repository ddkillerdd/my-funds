"""RFC-016 组合策略回测引擎 (Portfolio Strategy Simulator)

================================================================================
 目标
================================================================================
 将「分析模块的决策链路」原样搬到历史行情的"点内(point-in-time)"回放上，
 验证"这套决策在过去 N 天真实行情里表现如何、敢不敢按信号动态调仓"。

 它不生产建议，而是**服务分析模块**：
   - 分析模块回答"现在该怎么配置组合"(见 analyzer / decision.build_position_action)
   - 本模块回答"这套配置逻辑在过去行情中跑成什么样、可不可信、何时该谨慎"

================================================================================
 设计原则
================================================================================
  1. 点内无前视偏差 (No Lookahead Bias)
       - 模拟第 d 天时，只用 <= d 的净值数据算信号(动量/均线/RSI/波动率/回撤)。
       - 绝不使用 d 之后的"未来"数据 —— 这是回测可信的底线。
       - 每条信号需要至少 warmup 天的历史，不足则跳过该日(不产生伪信号)。

  2. 与决策模块同源 (Contract Consistency)
       - 信号: quant.compute_all(holding) → QuantIndicators(qi)  （与分析完全一致）
       - 动作: decision.build_position_action(qi, regime, current_weight, total_mv)
       - 市场状态: 复制 analyzer._detect_fund_regime 的纯量化推断
       - 这样"模拟结果"与"实盘决策"是同一套逻辑，模拟才有指导意义。

  3. 零 LLM、纯 CPU、幂等
       - 不调 LLM，可秒级回放多年行情，不占资源、结果可复现。

  4. 组合级再平衡 (Portfolio-level Rebalancing)
       - 每只基金独立给目标权重，再统一按"目标权重 / 总市值"执行调仓，
         体现系统"砍差的、加好的、控总风险"的组合能力，而非单基孤立。

  5. 可进化 (Evolvable)
       - 策略函数、执行模式、风险参数均可注入覆写，便于后续接入真实组合级
         regime(5大指数广度)、多种执行滑点模型、多策略对比。

================================================================================
 核心概念
================================================================================
  - window 天数: 只关注信号计算需要的回看长度(默认 252 交易日 ≈ 1年)。
  - 组合在每一天:
       组合净值 = Σ(每只基金份额 × 当日净值) + 现金
  - 再平衡: 每天按目标权重把"理论应持金额"重新分配到各基金(以当日净值买卖)。

 ⚠️ 简化说明(诚实披露):
   - 基金无法按日买卖(实际 T+1 确认、有申赎费)，本模块暂以"当日收盘价即时
     调仓"的理想化执行近似，侧重验证"信号方向是否合理"，而非精确套利收益。
   - 若要更贴近实盘的买入费率/赎回费/确认延迟，可通过 executor 注入扩展。
================================================================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from engine.models import (
    FundHolding,
    NavPoint,
    SimDaySnapshot,
    BacktestWindow,
    BacktestReport,
)
from engine.quant import compute_all
from engine.decision import (
    build_position_action,
    _f,
)
from engine.decision import BASE_WEIGHT, DD_HARD_STOP, DD_REDUCE_LO, VOL_HIGH_CAP

logger = logging.getLogger(__name__)


# =====================================================================
#  结果结构
# =====================================================================

@dataclass
class SimDayResult:
    """单日回放结果。"""
    date: str
    total_value: float                 # 组合总市值(含现金)
    cash: float                        # 现金
    holdings_value: float              # 持仓市值
    actions: Dict[str, dict] = field(default_factory=dict)   # code -> action dict
    target_weights: Dict[str, float] = field(default_factory=dict)  # code -> 目标权重(0~1)


@dataclass
class SimWindowResult:
    """单个窗口(strategy window)的回放汇总。"""
    window_days: int                       # 回放天数
    start_date: str
    end_date: str
    buy_hold_return_pct: float             # "一直不动等权持有"基准收益 %
    strategy_return_pct: float             # 系统动态调仓收益 %
    excess_return_pct: float               # 超额 = strategy - buy_hold
    max_drawdown_pct: float                # 策略最大回撤 %
    buy_hold_max_drawdown_pct: float       # 基准最大回撤 %
    daily: List[SimDayResult] = field(default_factory=list)
    final_weights: Dict[str, float] = field(default_factory=dict)  # 期末实际权重


# =====================================================================
#  市场状态推断 (复制 analyzer._detect_fund_regime 的纯量化逻辑)
# =====================================================================

def _detect_regime(qi) -> str:
    """单基金层面牛/熊/震荡推断(与分析模块一致的确定性逻辑)。"""
    if qi is None:
        return "sideways"
    trend_dir = qi.trend.trend_direction if qi.trend else "unknown"
    max_dd = abs(_f(qi, qi.risk.max_drawdown_pct if qi.risk else None))
    sharpe = _f(qi, qi.efficiency.sharpe_ratio if qi.efficiency else None)
    pb = qi.peer_benchmark
    excess = pb.excess_6m if pb else None

    if trend_dir == "up":
        if excess is not None and excess < -3:
            return "sideways"
        if excess is not None and excess >= 0:
            return "bull"
        if max_dd < 12 and sharpe > 0.3:
            return "bull"
        return "sideways"

    if trend_dir == "down":
        if max_dd >= 15 or sharpe < 0:
            return "bear"
        return "sideways"

    return "sideways"


# =====================================================================
#  数据准备: 每日点内切片
# =====================================================================

def _slice_history(navs: List[NavPoint], end_idx: int, warmup: int) -> List[NavPoint]:
    """取 [0, end_idx] 的历史(含 end_idx)，且长度至少 warmup。不足返回 []。"""
    if end_idx + 1 < warmup:
        return []
    return navs[:end_idx + 1]


def _build_last_known_value(histories: Dict[str, List[NavPoint]],
                               calendar: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
    """构造"最近已知净值"(carry-forward)映射。

    Args:
        histories: {code: [NavPoint,...]} 时间升序
        calendar: 回放日历(日期并集, 时间升序)。缺省用各基金历史日期并集。

    返回 {code: {date: 该日在 calendar 上当日或此前最近一个净值}}。
    确保 calendar 上每个日期都有条目(缺失基金日取它的 last-known), 既不视0
    也不用到未来(无前视)。这正确对齐了不同基金最后交易日不同造成的错位。
    """
    if calendar is None:
        calendar = sorted({p.date for h in histories.values() for p in h})
    out = {}
    for code, hist in histories.items():
        d2n = {}
        last = None
        j = 0
        n = len(hist)
        for d in calendar:
            # 推进 hist 指针到 <=d 的最后一条
            while j < n and hist[j].date <= d:
                if hist[j].nav is not None:
                    last = hist[j].nav
                j += 1
            if last is not None:
                d2n[d] = last
        out[code] = d2n
    return out


# =====================================================================
#  主入口
# =====================================================================

def simulate_portfolio(
    funds: List[dict],
    initial_amount: float = 200.0,
    windows: Optional[List[int]] = None,
    warmup: int = 252,
    target_vol: float = 0.15,
    friction_band_pp: float = 5.0,
    strategy: Optional[Callable] = None,
    executor: Optional[Callable] = None,
) -> Dict[str, SimWindowResult]:
    """对给定基金组合做多窗口点内策略回放。

    Args:
        funds: [
            {"code": "000311", "name": "...", "nav_history": [NavPoint,...](时间升序)},
            ...
        ]
        initial_amount: 初始总资金(元), 默认 200 = 模拟 50x4。等权分配到各基金。
        windows: 回放窗口天数列表, 如 [30, 90, 365]。取每只基金历史的最新 N 天回放。
        warmup: 信号回看天数(默认252交易日)。不足 warmup 的日期不产生信号(跳过)。
        target_vol: 波动率目标(默认0.15 -> L2 仓位)。
        friction_band_pp: 换手触发带(百分点, 默认5)。
        strategy: 可选覆盖"信号→动作"策略函数; 默认用 build_position_action。
                  签名: strategy(qi, regime, current_weight, total_mv) -> action dict
        executor: 可选覆盖"调仓执行"; 默认理想化即时调仓。
                  签名: executor(day_ctx, target_weights) -> None(原地修改持仓)

    Returns:
        {window_days: SimWindowResult, ...}
    """
    if not funds:
        return {}
    if windows is None:
        windows = [30, 90, 365]

    # 同一基金用同一份历史; 找出公共可回放的天数(所有基金都有数据)
    histories = {f["code"]: f["nav_history"] for f in funds}
    codes = list(histories.keys())

    # 每只基金按其自身历史长度独立回放? —— 为公平对比, 用"最短共同起点"
    # 简化: 对每个 window, 取"全部基金都至少有这些完整数据"的最近 window 天。
    # 若某基金历史不足 window, 该基金在窗口前段无净值 → 现金持有(不买入)。
    out: Dict[str, SimWindowResult] = {}
    for w in windows:
        out[w] = _simulate_window(
            codes=codes, histories=histories,
            window_days=w, initial_amount=initial_amount,
            warmup=warmup, target_vol=target_vol,
            friction_band_pp=friction_band_pp,
            strategy=strategy, executor=executor,
        )
    return out


def _simulate_window(codes, histories, window_days, initial_amount,
                     warmup, target_vol, friction_band_pp, strategy, executor) -> SimWindowResult:
    """回放单个窗口。

    正确性设计:
      - 回放日历 = 所有基金尾部 window 天日期的**并集**(各基金交易日可能不同,
        不能只取一只的日期, 否则其他基金缺该日会被当 0)。
      - 缺失日: 某基金在回放日无净值时, 向前取最近一个已知净值
        (carry-forward last-known, lkv), 既不视 0 也不用到未来(无前视偏差)。
        这也对齐了不同基金最后交易日不同造成的错位(如 018044 到 07-30、
        别的到 07-31)。
    """
    # 每基金尾部 window 天(不足则全部)
    tails = {c: histories[c][-window_days:] if len(histories[c]) >= window_days else histories[c]
             for c in codes}

    # 回放日历 = 各基金尾部日期的并集(时间升序)
    date_set = set()
    for c in codes:
        date_set.update(p.date for p in tails[c])
    dates = sorted(date_set)
    if not dates:
        return SimWindowResult(window_days=window_days, start_date="", end_date="",
                               buy_hold_return_pct=0, strategy_return_pct=0,
                               excess_return_pct=0, max_drawdown_pct=0,
                               buy_hold_max_drawdown_pct=0, daily=[], final_weights={})

    tail_nav = {c: {p.date: p.nav for p in tails[c]} for c in codes}
    full_by_code = {c: histories[c] for c in codes}
    date_to_idx = {c: {p.date: i for i, p in enumerate(histories[c])} for c in codes}
    # lkv[c][d] = calendar 上 d 当日或之前最近已知净值(缺失日 carry-forward)
    lkv = _build_last_known_value(full_by_code, calendar=dates)

    # 初始等权建仓(用窗口首日最近已知净值)
    nfunds = len(codes)
    per_fund = initial_amount / nfunds
    shares = {}
    first_nav = {}
    d0 = dates[0]
    for c in codes:
        fn = lkv[c].get(d0)
        first_nav[c] = fn
        shares[c] = per_fund / fn if fn and fn > 0 else 0.0
    cash = initial_amount - sum(shares[c] * (first_nav[c] or 0) for c in codes)
    buy_hold_values = {c: shares[c] for c in codes}   # 基准份额不随调仓变

    daily = []

    def nav_of(c, d):
        return lkv[c].get(d) or 0.0

    for d in dates:
        # ---- 点内信号(只用 <=d 数据) ----
        actions = {}
        total_now = sum(shares[c] * nav_of(c, d) for c in codes) + cash
        for c in codes:
            i = date_to_idx[c].get(d)
            if i is None:
                continue
            hist = _slice_history(full_by_code[c], i, warmup)
            if not hist:
                continue
            holding = FundHolding(
                fund_code=c, fund_name=c, fund_type="股票型",
                current_mv=0, cost=0, mv_ratio=0, nav_history=hist,
            )
            qi = compute_all(holding)
            regime = _detect_regime(qi)
            cur_mv = shares[c] * nav_of(c, d)
            cw = (cur_mv / total_now) if total_now > 0 else 0.0
            actions[c] = (strategy or _default_strategy)(
                qi, regime, cw, total_mv=total_now,
                target_vol=target_vol, friction_band_pp=friction_band_pp,
            )

        # ---- 目标权重 -> 归一化 -> 执行 ----
        target_weights = {
            c: actions[c]["target_weight"] if c in actions
               and actions[c].get("target_weight") is not None else 0.0
            for c in codes
        }
        tw_sum = sum(target_weights.values())
        if tw_sum > 1e-9:
            target_weights = {c: v / tw_sum for c, v in target_weights.items()}
        else:
            target_weights = {c: 0.0 for c in codes}

        cash = (executor or _default_executor)(shares, target_weights, lkv, d, total_now)

        holdings_value = sum(shares[c] * nav_of(c, d) for c in codes)
        total_value = holdings_value + cash
        daily.append(SimDayResult(
            date=d, total_value=total_value, cash=cash,
            holdings_value=holdings_value,
            actions=actions, target_weights=target_weights,
        ))

    # ---- 汇总 ----
    start_val = initial_amount
    final_res = daily[-1]
    strategy_ret = (final_res.total_value / start_val - 1) * 100 if start_val else 0.0

    d_last = dates[-1]
    bh_final = sum(buy_hold_values[c] * nav_of(c, d_last) for c in codes)
    bh_ret = (bh_final / start_val - 1) * 100 if start_val else 0.0

    max_dd = _max_drawdown([r.total_value for r in daily])
    bh_series = [sum(buy_hold_values[c] * nav_of(c, d) for c in codes) for d in dates]
    bh_max_dd = _max_drawdown(bh_series)

    final_weights = {}
    if final_res and final_res.holdings_value > 0:
        for c in codes:
            mv = shares[c] * nav_of(c, d_last)
            final_weights[c] = round(mv / final_res.holdings_value, 4)

    return SimWindowResult(
        window_days=window_days,
        start_date=dates[0] if dates else "",
        end_date=dates[-1] if dates else "",
        buy_hold_return_pct=round(bh_ret, 2),
        strategy_return_pct=round(strategy_ret, 2),
        excess_return_pct=round(strategy_ret - bh_ret, 2),
        max_drawdown_pct=round(max_dd, 2),
        buy_hold_max_drawdown_pct=round(bh_max_dd, 2),
        daily=daily,
        final_weights=final_weights,
    )



# =====================================================================
#  默认策略与执行(可注入覆写)
# =====================================================================

def _default_strategy(qi, regime, current_weight, total_mv=0.0,
                      target_vol=0.15, friction_band_pp=5.0, **kw) -> dict:
    """默认策略 = 直接调分析模块的 RFC-014 决策入口。"""
    return build_position_action(
        qi, regime, current_weight,
        target_vol=target_vol, friction_band_pp=friction_band_pp,
        total_mv=total_mv,
    )


def _default_executor(shares: Dict[str, float], target_weights: Dict[str, float],
                      nav_by_date: Dict[str, Dict[str, float]], date: str,
                      total_now: float) -> float:
    """默认执行: 把组合总资产按目标权重重新分配到各基金。

    理想化执行(无滑点/无费率/当日即时成交)。
      - 每只基金目标金额 = total_now × target_weight
      - 新份额 = 目标金额 / 当日净值
      - 现金 = total_now × (1 - Σ target_weight)  (多出的权重全部转现金, 不杠杆)
    """
    used = 0.0
    for c, w in target_weights.items():
        nav = nav_by_date.get(c, {}).get(date)
        if not nav or nav <= 0:
            shares[c] = 0.0
            continue
        target_amount = total_now * w
        shares[c] = target_amount / nav
        used += w
    cash = total_now * (1.0 - min(used, 1.0))
    return cash


def _max_drawdown(series: List[float]) -> float:
    """最大回撤 % (正数)。"""
    peak = -1e18
    max_dd = 0.0
    for v in series:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd


# =====================================================================
#  便捷: 从 SQLAlchemy 结果构建 funds 输入
# =====================================================================

def build_funds_input(rows_by_code: Dict[str, List[tuple]]) -> List[dict]:
    """把 {fund_code: [(date_str, nav_float), ...]} 转成 simulator 输入。

    Args:
        rows_by_code: {"000311": [(date, nav), ...], ...}(时间升序)

    Returns:
        [{"code":..., "name":..., "nav_history":[NavPoint,...]}, ...]
    """
    out = []
    for code, rows in rows_by_code.items():
        navs = [NavPoint(date=str(d), nav=float(n)) for d, n in rows]
        out.append({
            "code": code, "name": code, "nav_history": navs,
        })
    return out


# =====================================================================
#  一等公民入口: Simulator 类 + simulate() 便捷函数
#  (与分析模块 Analyzer / analyze() 平级, 产出 BacktestReport)
# =====================================================================

def _to_public_result(win: SimWindowResult, initial_amount: float) -> BacktestWindow:
    """把内部 SimWindowResult 转成对外 BacktestWindow(含每基金贡献与净值快照)。"""
    daily = []
    per_fund: Dict[str, Dict[str, float]] = {}
    # 每基金首末净值 -> 该基金区间收益
    first_nav: Dict[str, float] = {}
    last_nav: Dict[str, float] = {}
    for snap in win.daily:
        for code, weight in snap.target_weights.items():
            if code in last_nav and snap.date <= win.start_date:
                pass
        # 记录当日该基金净值(由 target_weights 的 key 反推)
    # 更稳: 用 final_weights 对应的基金集合; 逐日收集净值
    codes = set()
    for snap in win.daily:
        codes.update(snap.target_weights.keys())
    # 从首末日快照拿该基金净值(经权重=1的天不保证, 故用 daily 内 target_weights 反查不可靠)
    # 改为: per_fund 收益用"期末权重×期末总市值"推算等价口径 —— 简化用 return 曲线
    for snap in win.daily:
        daily.append(SimDaySnapshot(
            date=snap.date,
            total_value=round(snap.total_value, 4),
            cash=round(snap.cash, 4),
            holdings_value=round(snap.holdings_value, 4),
            target_weights={k: round(v, 4) for k, v in snap.target_weights.items()},
            actions={k: (v.get("action") if isinstance(v, dict) else v)
                     for k, v in snap.actions.items()},
        ))
    # per_fund 贡献: 用最终权重 ± 无法精确到每基收益, 给 return_pct 由窗口整体承担,
    # 这里按"期末每基市值占比"给出权重口径
    total_hv = win.daily[-1].holdings_value if win.daily else 0
    for code, w in win.final_weights.items():
        per_fund[code] = {
            "final_weight_pct": round(w * 100, 2),
        }
        # 单基区间收益: 若能取到该基当日净值
    return BacktestWindow(
        window_days=win.window_days,
        start_date=win.start_date,
        end_date=win.end_date,
        initial_amount=initial_amount,
        final_value=round(win.daily[-1].total_value, 2) if win.daily else 0.0,
        strategy_return_pct=win.strategy_return_pct,
        buy_hold_return_pct=win.buy_hold_return_pct,
        excess_return_pct=win.excess_return_pct,
        strategy_max_drawdown_pct=win.max_drawdown_pct,
        buy_hold_max_drawdown_pct=win.buy_hold_max_drawdown_pct,
        final_weights={k: round(v, 4) for k, v in win.final_weights.items()},
        daily=daily,
        per_fund=per_fund,
    )


class Simulator:
    """组合策略回测器 —— 分析模块的一等公民入口。

    用法与 Analyzer 对齐:
        sim = Simulator(initial_amount=200, windows=[30, 90, 365])
        report = sim.simulate(funds)          # -> BacktestReport
        report.windows[90].strategy_return_pct

    核心特性:
      - 零 LLM、纯 CPU、幂等, 秒级回放多年历史
      - 与分析模块同源信号(quant.compute_all + decision.build_position_action)
      - 点内无前视偏差 + carry-forward 对齐不同基金交易日
      - 策略/执行可注入覆写(可进化)
    """

    def __init__(
        self,
        initial_amount: float = 200.0,
        windows: Optional[List[int]] = None,
        warmup: int = 252,
        target_vol: float = 0.15,
        friction_band_pp: float = 5.0,
        strategy: Optional[Callable] = None,
        executor: Optional[Callable] = None,
    ):
        self.initial_amount = initial_amount
        self.windows = windows or [30, 90, 365]
        self.warmup = warmup
        self.target_vol = target_vol
        self.friction_band_pp = friction_band_pp
        self.strategy = strategy
        self.executor = executor

    def simulate(self, funds: List[dict]) -> BacktestReport:
        """对给定基金组合做多窗口点内策略回放, 返回 BacktestReport。"""
        import time
        t0 = time.time()
        raw = simulate_portfolio(
            funds,
            initial_amount=self.initial_amount,
            windows=self.windows,
            warmup=self.warmup,
            target_vol=self.target_vol,
            friction_band_pp=self.friction_band_pp,
            strategy=self.strategy,
            executor=self.executor,
        )
        windows = {
            wd: _to_public_result(win, self.initial_amount)
            for wd, win in raw.items()
        }
        # summary: 多窗口超额
        excesses = [w.excess_return_pct for w in windows.values()]
        nfunds = len(funds)
        initial_w = {f["code"]: round(1.0 / nfunds, 4) for f in funds} if nfunds else {}
        report = BacktestReport(
            generated_at=__import__("datetime").datetime.now().isoformat(timespec="seconds"),
            duration_seconds=round(time.time() - t0, 2),
            initial_amount=self.initial_amount,
            initial_weights=initial_w,
            target_vol=self.target_vol,
            warmup=self.warmup,
            windows=windows,
            summary={
                "best_excess_pct": round(max(excesses), 2) if excesses else 0.0,
                "worst_excess_pct": round(min(excesses), 2) if excesses else 0.0,
                "avg_excess_pct": round(sum(excesses) / len(excesses), 2) if excesses else 0.0,
                "windows": self.windows,
            },
        )
        return report


def simulate(
    funds: List[dict],
    initial_amount: float = 200.0,
    windows: Optional[List[int]] = None,
    warmup: int = 252,
    target_vol: float = 0.15,
    friction_band_pp: float = 5.0,
    strategy: Optional[Callable] = None,
    executor: Optional[Callable] = None,
) -> BacktestReport:
    """便捷入口: 一行跑回测。与分析模块 analyze() 对齐。

    Args:
        funds: [{"code":..., "name":..., "nav_history":[NavPoint,...]}(时间升序)]
        initial_amount: 初始总资金(元), 等权分配
        windows: 回放窗口天数列表
        warmup: 信号回看天数
        target_vol: 波动率目标
        friction_band_pp: 换手触发带
        strategy / executor: 可注入覆写

    Returns:
        BacktestReport(含多窗口详细结果与 summary)
    """
    return Simulator(
        initial_amount=initial_amount,
        windows=windows,
        warmup=warmup,
        target_vol=target_vol,
        friction_band_pp=friction_band_pp,
        strategy=strategy,
        executor=executor,
    ).simulate(funds)
