"""
Quantitative Indicators Engine

Pure Python computation — zero LLM involvement.
All 32+ indicators computed from nav_history alone.

Input: FundHolding (with nav_history) + optional benchmark_history
Output: QuantIndicators (complete, with nulls where data insufficient)
"""

from __future__ import annotations

import numpy as np
import logging
from typing import List, Optional, Tuple, Dict

from .models import (
    NavPoint,
    FundHolding,
    QuantIndicators,
    TrendIndicators,
    MacdIndicators,
    MomentumIndicators,
    RiskIndicators,
    ReturnIndicators,
    EfficiencyIndicators,
    BenchmarkIndicators,
)

logger = logging.getLogger(__name__)


def _nav_to_series(nav_history: List[NavPoint]) -> np.ndarray:
    """Convert NavPoint list to numpy array of nav values (most recent last)."""
    if not nav_history:
        return np.array([])
    arr = np.array([p.nav for p in nav_history], dtype=np.float64)
    return arr


def _nav_to_returns(navs: np.ndarray) -> np.ndarray:
    """Daily log returns from nav series."""
    if len(navs) < 2:
        return np.array([])
    return np.diff(np.log(navs))


def _nav_to_simple_returns(navs: np.ndarray) -> np.ndarray:
    """Daily simple returns from nav series."""
    if len(navs) < 2:
        return np.array([])
    return np.diff(navs) / navs[:-1]


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling mean, returns array of same length (first window-1 are NaN)."""
    if len(arr) < window:
        return np.full(len(arr), np.nan)
    result = np.full(len(arr), np.nan)
    cumsum = np.cumsum(np.insert(arr, 0, 0))
    result[window - 1:] = (cumsum[window:] - cumsum[:-window]) / window
    return result


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average."""
    if len(arr) < span:
        return np.full(len(arr), np.nan)
    alpha = 2.0 / (span + 1)
    result = np.full(len(arr), np.nan)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


# ============================================================
#  TREND INDICATORS
# ============================================================

def compute_trend(navs: np.ndarray, nav_history: List[NavPoint]) -> TrendIndicators:
    """Compute MA, trend strength, direction from nav series."""
    t = TrendIndicators()
    n = len(navs)

    if n < 2:
        t.notes.append("净值数据不足2天，无法计算趋势指标")
        return t

    t.current_nav = navs[-1]

    # MA lines
    for window, attr in [(5, 'ma5'), (10, 'ma10'), (20, 'ma20'), (60, 'ma60'), (120, 'ma120')]:
        if n >= window:
            setattr(t, attr, round(float(_rolling_mean(navs, window)[-1]), 6))

    # MA status (current_nav vs all available MAs)
    mas = []
    for attr in ['ma5', 'ma10', 'ma20', 'ma60', 'ma120']:
        val = getattr(t, attr)
        if val is not None:
            mas.append((attr, val))

    if mas and t.current_nav:
        above_all = all(t.current_nav > v for _, v in mas)
        below_all = all(t.current_nav < v for _, v in mas)
        if above_all:
            t.ma_status = "above_all"
        elif below_all:
            t.ma_status = "below_all"
        else:
            above_short = all(t.current_nav > v for a, v in mas if a in ('ma5', 'ma10'))
            if above_short:
                t.ma_status = "above_short"
            else:
                below_short = all(t.current_nav < v for a, v in mas if a in ('ma5', 'ma10'))
                t.ma_status = "below_short" if below_short else "mixed"

    # MA deviation
    if t.ma20 and t.current_nav:
        t.ma_deviation_pct = round(float((t.current_nav / t.ma20 - 1) * 100), 4)

    # Trend strength (0-100)
    # Based on: MA alignment score + recent return strength + price position
    if n >= 20:
        score = 50.0
        # MA alignment
        if t.ma_status == "above_all":
            score += 20
        elif t.ma_status == "below_all":
            score -= 20
        elif t.ma_status == "above_short":
            score += 10
        elif t.ma_status == "below_short":
            score -= 10

        # Recent return strength
        if n >= 10:
            ret_10d = (navs[-1] / navs[-10] - 1) * 100
            score += min(max(ret_10d * 2, -20), 20)

        t.trend_strength = int(max(0, min(100, round(score))))

    # Trend direction
    if n >= 20 and t.ma20:
        if t.current_nav > t.ma20 * 1.005:
            t.trend_direction = "up"
        elif t.current_nav < t.ma20 * 0.995:
            t.trend_direction = "down"
        else:
            t.trend_direction = "sideways"

    # Price position in range
    if n >= 60:
        high = np.max(navs[-60:])
        low = np.min(navs[-60:])
        if high > low:
            t.price_position_pct = round(float((t.current_nav - low) / (high - low) * 100), 1)

    # Consecutive direction days (based on day-over-day)
    if n >= 5:
        up_streak = 0
        down_streak = 0
        for i in range(len(navs) - 1, 0, -1):
            if navs[i] > navs[i - 1]:
                up_streak += 1
            else:
                break
        for i in range(len(navs) - 1, 0, -1):
            if navs[i] < navs[i - 1]:
                down_streak += 1
            else:
                break
        t.consecutive_direction_days = up_streak if up_streak > down_streak else -down_streak

    return t


def compute_macd(navs: np.ndarray) -> MacdIndicators:
    """Compute MACD (12, 26, 9) from nav series."""
    m = MacdIndicators()

    if len(navs) < 26:
        m.notes.append("净值数据不足26天，无法计算MACD")
        return m

    ema12 = _ema(navs, 12)
    ema26 = _ema(navs, 26)
    dif = ema12 - ema26
    dea = _ema(dif[~np.isnan(dif)], 9)

    # Align DEA to the end of DIF
    dea_aligned = np.full(len(dif), np.nan)
    start = len(dif) - len(dea)
    if start >= 0:
        dea_aligned[start:] = dea

    m.dif = round(float(dif[-1]), 6)
    m.dea = round(float(dea_aligned[-1]), 6)
    m.histogram = round(float((dif[-1] - dea_aligned[-1]) * 2), 6)

    # Signal determination
    if len(dif) >= 3:
        if dif[-1] > dea_aligned[-1] and dif[-2] <= dea_aligned[-2]:
            m.signal = "golden_cross_inactive"  # just crossed but might not be recent
        elif dif[-1] < dea_aligned[-1] and dif[-2] >= dea_aligned[-2]:
            m.signal = "death_cross_inactive"
        elif dif[-1] > dea_aligned[-1]:
            m.signal = "golden_cross_active"
        elif dif[-1] < dea_aligned[-1]:
            m.signal = "death_cross_active"
        else:
            m.signal = "neutral"

    # Divergence detection (price vs DIF)
    if len(navs) >= 40 and len(dif) >= 40 and not np.isnan(dif[-1]):
        # Bullish divergence: price makes lower low, DIF makes higher low
        lookback = min(30, len(dif))
        recent_dif = dif[-lookback:]
        recent_navs = navs[-lookback:]
        # Simplified: check if recent trend in price vs DIF diverges
        dif_trend = recent_dif[-1] - recent_dif[0]
        nav_trend = recent_navs[-1] - recent_navs[0]
        if nav_trend < 0 and dif_trend > 0:
            m.divergence_type = "bullish_divergence"
        elif nav_trend > 0 and dif_trend < 0:
            m.divergence_type = "bearish_divergence"

    return m


# ============================================================
#  MOMENTUM INDICATORS
# ============================================================

def compute_momentum(navs: np.ndarray, returns: np.ndarray) -> MomentumIndicators:
    """Compute RSI, win rates, Bollinger Bands."""
    mo = MomentumIndicators()

    n = len(navs)

    # RSI(14)
    if n >= 15:
        deltas = np.diff(navs)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])

        if avg_loss == 0:
            mo.rsi_14 = 100.0
        else:
            rs = avg_gain / avg_loss
            mo.rsi_14 = round(float(100 - 100 / (1 + rs)), 1)

        if mo.rsi_14 is not None:
            if mo.rsi_14 > 70:
                mo.rsi_signal = "overbought"
            elif mo.rsi_14 < 30:
                mo.rsi_signal = "oversold"
            else:
                mo.rsi_signal = "neutral"

    # Win rates
    if n >= 21:
        up_count_20 = int(np.sum((np.diff(navs[-21:]) > 0)))
        mo.win_rate_20 = round(float(up_count_20 / 20 * 100), 1)

    if n >= 61:
        up_count_60 = int(np.sum((np.diff(navs[-61:]) > 0)))
        mo.win_rate_60 = round(float(up_count_60 / 60 * 100), 1)

    # Consecutive days
    if n >= 2:
        up_streak = 0
        down_streak = 0
        deltas = np.diff(navs)
        for i in range(len(deltas) - 1, -1, -1):
            if deltas[i] > 0:
                up_streak += 1
            else:
                break
        for i in range(len(deltas) - 1, -1, -1):
            if deltas[i] < 0:
                down_streak += 1
            else:
                break
        mo.consecutive_up_days = up_streak
        mo.consecutive_down_days = down_streak

    # Bollinger Bands (20, 2)
    if n >= 20:
        ma20 = _rolling_mean(navs, 20)
        # 防 NaN: 窗口样本 <2 时 np.std(ddof=1) 触发 "Degrees of freedom <= 0"
        # → RuntimeWarning + NaN。早期窗口样本不足置 NaN 不影响 (尾部 std20[-1]
        # 始终是完整 20 窗口, 供 bollinger_upper/lower 使用)。
        std20 = np.array([
            float(np.std(navs[max(0, i - 19):i + 1], ddof=1))
            if len(navs[max(0, i - 19):i + 1]) >= 2 else np.nan
            for i in range(n)
        ])

        mo.bollinger_mid = round(float(ma20[-1]), 6)
        mo.bollinger_upper = round(float(ma20[-1] + 2 * std20[-1]), 6)
        mo.bollinger_lower = round(float(ma20[-1] - 2 * std20[-1]), 6)

        # Position
        if navs[-1] > mo.bollinger_upper:
            mo.bollinger_position = "above_upper"
        elif navs[-1] > mo.bollinger_mid:
            mo.bollinger_position = "upper_half"
        elif navs[-1] > mo.bollinger_lower:
            mo.bollinger_position = "lower_half"
        else:
            mo.bollinger_position = "below_lower"

        # Band width
        if mo.bollinger_mid > 0:
            mo.bollinger_width_pct = round(float((mo.bollinger_upper - mo.bollinger_lower) / mo.bollinger_mid * 100), 2)

    return mo


# ============================================================
#  RISK INDICATORS
# ============================================================

def compute_risk(navs: np.ndarray, returns: np.ndarray, nav_history: List[NavPoint]) -> RiskIndicators:
    """Compute volatility, drawdown, VaR, CVaR, Ulcer Index."""
    r = RiskIndicators()

    n = len(returns)

    if n < 5:
        r.notes.append("收益数据不足5天，无法计算风险指标")
        return r

    trading_days_per_year = 252
    daily_returns_simple = _nav_to_simple_returns(navs)

    # Annualized volatility
    daily_vol = float(np.std(returns, ddof=1))
    r.annual_volatility_pct = round(daily_vol * np.sqrt(trading_days_per_year) * 100, 2)

    if n >= 20:
        # Volatility regime classification
        if r.annual_volatility_pct < 10:
            r.volatility_regime = "low"
        elif r.annual_volatility_pct < 20:
            r.volatility_regime = "medium"
        elif r.annual_volatility_pct < 35:
            r.volatility_regime = "high"
        else:
            r.volatility_regime = "extreme"

    # Downside volatility
    neg_returns = returns[returns < 0]
    # 防 NaN: len==1 时 np.std(ddof=1) 自由度=0 → RuntimeWarning + NaN。
    if len(neg_returns) > 1:
        downside_vol = float(np.std(neg_returns, ddof=1))
        r.downside_volatility_pct = round(downside_vol * np.sqrt(trading_days_per_year) * 100, 2)

    # Max drawdown
    if n >= 10:
        cumulative = np.cumprod(1 + daily_returns_simple) if len(daily_returns_simple) == len(navs) - 1 else np.array(navs) / navs[0]
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak

        max_dd_idx = int(np.argmin(drawdown))
        r.max_drawdown_pct = round(float(drawdown[max_dd_idx] * 100), 2)

        # Start date: last peak before the drawdown
        if max_dd_idx > 0:
            try:
                peak_start = int(np.where(drawdown[:max_dd_idx] == 0)[0][-1])
                if peak_start < len(nav_history) and peak_start + 1 < len(nav_history):
                    r.max_drawdown_start = nav_history[peak_start + 1].date  # +1 for nav→return alignment
            except (IndexError, ValueError):
                pass

        # End date (lowest point)
        if max_dd_idx + 1 < len(nav_history):
            r.max_drawdown_end = nav_history[max_dd_idx + 1].date

        # Recovery time
        if max_dd_idx < len(drawdown) - 1:
            recovery = np.where(drawdown[max_dd_idx + 1:] == 0)[0]
            if len(recovery) > 0:
                r.max_drawdown_recovery_days = int(recovery[0])

        # Duration
        if r.max_drawdown_start and r.max_drawdown_end:
            from datetime import datetime
            try:
                start = datetime.strptime(r.max_drawdown_start, "%Y-%m-%d")
                end = datetime.strptime(r.max_drawdown_end, "%Y-%m-%d")
                r.max_drawdown_duration_days = (end - start).days
            except ValueError:
                pass

        # Current drawdown
        r.current_drawdown_pct = round(float(drawdown[-1] * 100), 2)

    # Value at Risk (95% daily)
    if n >= 30:
        r.var_95_daily_pct = round(float(np.percentile(returns, 5) * 100), 2)

    # Conditional VaR (expected shortfall)
    if n >= 30:
        tail = returns[returns <= np.percentile(returns, 5)]
        if len(tail) > 0:
            r.cvar_95_daily_pct = round(float(np.mean(tail) * 100), 2)

    # Ulcer Index
    if n >= 20 and len(daily_returns_simple) > 0:
        cum_ret = np.cumprod(1 + daily_returns_simple)
        peak_so_far = np.maximum.accumulate(cum_ret)
        pct_drawdown = (cum_ret - peak_so_far) / peak_so_far * 100
        r.ulcer_index = round(float(np.sqrt(np.mean(pct_drawdown ** 2))), 2)

    return r


# ============================================================
#  RETURN INDICATORS
# ============================================================

def compute_returns(navs: np.ndarray, returns: np.ndarray) -> ReturnIndicators:
    """Compute period returns, annual return, win rate, P/L ratio."""
    ret = ReturnIndicators()

    n = len(navs)

    if n < 5:
        ret.notes.append("净值数据不足5天，无法计算收益指标")
        return ret

    trading_days_per_year = 252

    # Period returns
    periods = {
        'return_1m_pct': 22,
        'return_3m_pct': 66,
        'return_6m_pct': 126,
        'return_1y_pct': trading_days_per_year,
    }

    for attr, days in periods.items():
        if n >= days + 1:
            setattr(ret, attr, round(float((navs[-1] / navs[-days - 1] - 1) * 100), 2))

    # Cumulative return (since beginning)
    if n > 1:
        ret.cumulative_return_pct = round(float((navs[-1] / navs[0] - 1) * 100), 2)

    # Annualized return (log returns)
    if n > trading_days_per_year:
        total_return_log = np.log(navs[-1] / navs[0])
        ret.annual_return_pct = round(float(total_return_log / n * trading_days_per_year * 100), 2)
    elif n > 60:
        total_return_log = np.log(navs[-1] / navs[0])
        ret.annual_return_pct = round(float(total_return_log / n * trading_days_per_year * 100), 2)

    # Monthly win rate
    if n > 60:
        daily_ret = _nav_to_simple_returns(navs)
        monthly_ret = []
        for i in range(0, len(daily_ret), 22):
            if i + 22 <= len(daily_ret):
                monthly_ret.append(np.prod(1 + daily_ret[i:i + 22]) - 1)
        if monthly_ret:
            positive_months = int(np.sum(np.array(monthly_ret) > 0))
            ret.monthly_win_rate = round(float(positive_months / len(monthly_ret) * 100), 1)

    # Profit/Loss ratio
    daily_ret = _nav_to_simple_returns(navs)
    if len(daily_ret) > 0:
        gains = daily_ret[daily_ret > 0]
        losses = np.abs(daily_ret[daily_ret < 0])
        if len(losses) > 0 and len(gains) > 0:
            ret.profit_loss_ratio = round(float(np.mean(gains) / np.mean(losses)), 2)
        if n >= 2:
            ret.best_day_pct = round(float(np.max(daily_ret) * 100), 2)
            ret.worst_day_pct = round(float(np.min(daily_ret) * 100), 2)

    return ret


# ============================================================
#  EFFICIENCY INDICATORS
# ============================================================

def compute_efficiency(returns: np.ndarray, risk: RiskIndicators) -> EfficiencyIndicators:
    """Compute Sharpe, Sortino, Calmar, Information Ratio, Omega."""
    e = EfficiencyIndicators()

    n = len(returns)
    if n < 30:
        e.notes.append("收益数据不足30天，无法可靠计算效率指标")
        return e

    trading_days_per_year = 252
    daily_mean = float(np.mean(returns))
    daily_std = float(np.std(returns, ddof=1))
    risk_free_rate_daily = 0.02 / trading_days_per_year  # 2% annual

    excess_mean = daily_mean - risk_free_rate_daily

    # Sharpe Ratio
    if daily_std > 0:
        e.sharpe_ratio = round(float(excess_mean / daily_std * np.sqrt(trading_days_per_year)), 2)

    # Sortino Ratio
    neg_returns = returns[returns < 0]
    # 防 NaN: len==1 时 np.std(ddof=1) 自由度=0 → RuntimeWarning + NaN。
    if len(neg_returns) > 1:
        downside_std = float(np.std(neg_returns, ddof=1))
        if downside_std > 0:
            e.sortino_ratio = round(float(excess_mean / downside_std * np.sqrt(trading_days_per_year)), 2)

    # Calmar Ratio (return / max drawdown)
    if risk.max_drawdown_pct and risk.max_drawdown_pct < 0:
        # annual_return_pct already stored, but let's compute from returns
        ann_ret = float(daily_mean * trading_days_per_year * 100)
        e.calmar_ratio = round(float(ann_ret / abs(risk.max_drawdown_pct)), 2)

    # Omega Ratio
    if n > 0:
        target = 0
        excess_returns = returns - target
        upside = np.sum(excess_returns[excess_returns > 0])
        downside = np.abs(np.sum(excess_returns[excess_returns < 0]))
        if downside > 0:
            e.omega_ratio = round(float(upside / downside), 2)

    return e


# ============================================================
#  BENCHMARK COMPARISON
# ============================================================

def compute_benchmark(
    fund_navs: np.ndarray,
    benchmark_navs: Optional[np.ndarray],
    fund_returns: np.ndarray,
) -> Optional[BenchmarkIndicators]:
    """Compute alpha, beta, tracking error, capture ratios vs benchmark."""
    if benchmark_navs is None or len(benchmark_navs) < len(fund_navs):
        return None

    b = BenchmarkIndicators()

    # Align lengths
    fund_ret = _nav_to_simple_returns(fund_navs)
    bench_ret = _nav_to_simple_returns(benchmark_navs)
    min_len = min(len(fund_ret), len(bench_ret))
    fund_ret = fund_ret[-min_len:]
    bench_ret = bench_ret[-min_len:]

    if min_len < 20:
        b.notes.append("基准数据不足20天，无法可靠计算")
        return b

    # Excess return (cumulative)
    fund_cum = np.prod(1 + fund_ret) - 1
    bench_cum = np.prod(1 + bench_ret) - 1
    b.excess_return_pct = round(float((fund_cum - bench_cum) * 100), 2)

    # Beta
    cov = np.cov(fund_ret, bench_ret)
    if cov.shape == (2, 2) and cov[1, 1] > 0:
        b.beta = round(float(cov[0, 1] / cov[1, 1]), 2)

        # Alpha (annualized)
        fund_mean = np.mean(fund_ret) * 252
        bench_mean = np.mean(bench_ret) * 252
        b.alpha = round(float(fund_mean - b.beta * bench_mean), 2)

    # Tracking error
    diff = fund_ret - bench_ret
    b.tracking_error = round(float(np.std(diff, ddof=1) * np.sqrt(252) * 100), 2)

    # Capture ratios
    up_markets = bench_ret > 0
    down_markets = bench_ret < 0

    if np.sum(up_markets) > 0:
        b.capture_up = round(float(np.mean(fund_ret[up_markets]) / np.mean(bench_ret[up_markets]) * 100), 1)

    if np.sum(down_markets) > 0:
        b.capture_down = round(float(np.mean(fund_ret[down_markets]) / np.mean(bench_ret[down_markets]) * 100), 1)

    return b


# ============================================================
#  MAIN ENTRY POINT
# ============================================================

def compute_all(holding: FundHolding) -> QuantIndicators:
    """
    Compute all quantitative indicators for a single fund holding.

    Args:
        holding: FundHolding with nav_history populated

    Returns:
        QuantIndicators with all computable fields filled
    """
    nav_history = holding.nav_history
    navs = _nav_to_series(nav_history)
    returns = _nav_to_returns(navs)

    n = len(navs)

    # Determine data quality
    if n >= 252:
        quality = "good"
    elif n >= 120:
        quality = "adequate"
    elif n >= 60:
        quality = "sparse"
    else:
        quality = "insufficient"

    # Compute pnl
    pnl_amount = holding.current_mv - holding.cost
    pnl_pct = (pnl_amount / holding.cost * 100) if holding.cost > 0 else 0.0

    # Build result
    indicators = QuantIndicators(
        fund_code=holding.fund_code,
        fund_name=holding.fund_name,
        fund_type=holding.fund_type,
        current_mv=holding.current_mv,
        cost=holding.cost,
        mv_ratio=holding.mv_ratio,
        pnl_amount=round(pnl_amount, 2),
        pnl_pct=round(pnl_pct, 2),
        is_money_fund=holding.is_money_fund,
        nav_history_days=n,
        data_quality=quality,
    )

    # Compute each category
    indicators.trend = compute_trend(navs, nav_history)
    indicators.macd = compute_macd(navs)
    indicators.momentum = compute_momentum(navs, returns)
    indicators.risk = compute_risk(navs, returns, nav_history)
    indicators.returns = compute_returns(navs, returns)
    indicators.efficiency = compute_efficiency(returns, indicators.risk)

    # Benchmark (if available)
    if holding.benchmark_history:
        bench_navs = _nav_to_series(holding.benchmark_history)
        indicators.benchmark = compute_benchmark(navs, bench_navs, returns)

    # Collect all notes
    for cat in [indicators.trend, indicators.macd, indicators.momentum,
                indicators.risk, indicators.returns, indicators.efficiency]:
        indicators.all_notes.extend(cat.notes)
    if indicators.benchmark:
        indicators.all_notes.extend(indicators.benchmark.notes)

    return indicators


def build_ground_truth(holdings: List[FundHolding]) -> Dict[str, any]:
    """
    Compute ground truth for all holdings.
    Returns a dict ready for the PortfolioGroundTruth portion of the report.
    """
    per_fund = []
    for h in holdings:
        qi = compute_all(h)
        per_fund.append(qi)

    # Portfolio aggregates
    total_mv = sum(q.current_mv for q in per_fund)
    total_cost = sum(q.cost for q in per_fund)
    total_pnl = total_mv - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
    holding_count = len(holdings)
    active_count = sum(1 for h in holdings if not h.is_money_fund)
    money_fund_count = holding_count - active_count

    # Data range
    all_dates = []
    for h in holdings:
        for np_point in h.nav_history:
            all_dates.append(np_point.date)
    if all_dates:
        all_dates.sort()
        data_start = all_dates[0]
        data_end = all_dates[-1]
        from datetime import datetime
        try:
            data_days = (datetime.strptime(data_end, "%Y-%m-%d") - datetime.strptime(data_start, "%Y-%m-%d")).days
        except ValueError:
            data_days = len(all_dates) // len(holdings)
    else:
        data_start = None
        data_end = None
        data_days = 0

    # Data quality
    qualities = [q.data_quality for q in per_fund]
    if all(q == "good" for q in qualities):
        overall_quality = "good"
    elif all(q != "insufficient" for q in qualities):
        overall_quality = "adequate"
    elif sum(1 for q in qualities if q == "insufficient") <= len(qualities) // 2:
        overall_quality = "sparse"
    else:
        overall_quality = "insufficient"

    return {
        "per_fund": per_fund,
        "total_market_value": round(total_mv, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "holding_count": holding_count,
        "active_count": active_count,
        "money_fund_count": money_fund_count,
        "data_start_date": data_start,
        "data_end_date": data_end,
        "data_days": data_days,
        "overall_data_quality": overall_quality,
    }
