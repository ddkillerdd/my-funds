"""
Portfolio-Level Quantitative Analysis

Correlation matrix, concentration (HHI), efficient frontier (Monte Carlo).
Pure Python — zero LLM involvement.
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Optional, Tuple
import logging

from .models import (
    FundHolding,
    CorrelationData,
    ConcentrationData,
    EfficientFrontierData,
)

logger = logging.getLogger(__name__)


def correlation_matrix(holdings: List[FundHolding]) -> CorrelationData:
    """
    Compute pairwise correlation matrix of fund daily returns.
    Only includes non-money-fund holdings with >= 30 days of nav history.
    """
    corr = CorrelationData()

    # Filter to active funds with sufficient data
    active = [h for h in holdings if not h.is_money_fund and len(h.nav_history) >= 30]
    if len(active) < 2:
        corr.notes.append("活跃基金不足2只，无法计算相关性矩阵")
        return corr

    # Align all nav series to common date range
    # Simple: use min length
    nav_series = {}
    for h in active:
        navs = np.array([p.nav for p in h.nav_history])
        nav_series[h.fund_code] = navs

    min_len = min(len(v) for v in nav_series.values())
    if min_len < 2:
        corr.notes.append("对齐后数据点不足")
        return corr

    # Truncate to min length, compute returns
    returns = {}
    for code, navs in nav_series.items():
        truncated = navs[-min_len:]
        ret = np.diff(truncated) / truncated[:-1]
        returns[code] = ret

    codes = list(returns.keys())
    n_codes = len(codes)
    matrix = [[None] * n_codes for _ in range(n_codes)]

    for i in range(n_codes):
        matrix[i][i] = 1.0
        for j in range(i + 1, n_codes):
            try:
                corr_val = float(np.corrcoef(returns[codes[i]], returns[codes[j]])[0, 1])
                if np.isnan(corr_val):
                    corr_val = None
                else:
                    corr_val = round(corr_val, 4)
            except Exception:
                corr_val = None
            matrix[i][j] = corr_val
            matrix[j][i] = corr_val

    # Average pairwise correlation
    pair_corrs = []
    high_corr_pairs = []
    for i in range(n_codes):
        for j in range(i + 1, n_codes):
            if matrix[i][j] is not None:
                pair_corrs.append(matrix[i][j])
                if matrix[i][j] >= 0.7:
                    high_corr_pairs.append({
                        "pair": [codes[i], codes[j]],
                        "correlation": matrix[i][j],
                    })

    corr.matrix = matrix
    corr.labels = codes
    corr.avg_pairwise_corr = round(float(np.mean(pair_corrs)), 4) if pair_corrs else None
    corr.high_corr_pairs = high_corr_pairs

    return corr


def concentration(holdings: List[FundHolding]) -> ConcentrationData:
    """
    Compute concentration metrics:
    - HHI (Herfindahl-Hirschman Index)
    - Top-1 / Top-3 share
    """
    conc = ConcentrationData()

    if not holdings:
        conc.notes.append("无持仓数据")
        return conc

    # Normalize weights to 1.0
    total_mv = sum(h.current_mv for h in holdings)
    if total_mv <= 0:
        conc.notes.append("组合市值为0")
        return conc

    weights = np.array([h.current_mv / total_mv for h in holdings])

    # HHI
    hhi = float(np.sum(weights ** 2))

    # Normalize HHI to 1/n ~ 1 range: HHI_norm = (HHI - 1/n) / (1 - 1/n)
    n = len(holdings)
    if n > 1:
        hhi_norm = (hhi - 1 / n) / (1 - 1 / n)
    else:
        hhi_norm = hhi

    conc.hhi_index = round(float(hhi), 4)

    if hhi_norm < 0.1:
        conc.hhi_label = "low"
    elif hhi_norm < 0.25:
        conc.hhi_label = "moderate"
    elif hhi_norm < 0.5:
        conc.hhi_label = "high"
    else:
        conc.hhi_label = "extreme"

    # Top shares
    sorted_weights = sorted(weights, reverse=True)
    conc.top1_pct = round(float(sorted_weights[0] * 100), 1)
    if len(sorted_weights) >= 3:
        conc.top3_pct = round(float(sum(sorted_weights[:3]) * 100), 1)

    return conc


def efficient_frontier(
    holdings: List[FundHolding],
    num_portfolios: int = 5000,
    risk_free_rate: float = 0.02,
) -> EfficientFrontierData:
    """
    Monte Carlo simulation to approximate the efficient frontier.

    For each active fund, compute annualized return and volatility.
    Then simulate random weight combinations to find:
    - Max Sharpe ratio portfolio
    - Min volatility portfolio
    - Distance of current portfolio from the frontier
    """
    ef = EfficientFrontierData(simulations=num_portfolios)

    # Filter to active funds with sufficient data
    active = [h for h in holdings if not h.is_money_fund and len(h.nav_history) >= 60]
    if len(active) < 2:
        ef.notes.append("活跃基金不足2只（均需≥60天净值历史），无法计算有效前沿")
        return ef

    num_assets = len(active)
    # Limit to prevent combinatorial explosion; skip money funds but keep 2+ actives
    if num_assets > 6:
        active = active[:6]  # Cap at 6 for reasonable simulation
        ef.notes.append("基金超过6只，截取前6只进行有效前沿模拟")

    # Compute annualized returns and covariance
    all_ret_series = []
    codes = []
    for h in active:
        navs = np.array([p.nav for p in h.nav_history])
        rets = np.diff(navs) / navs[:-1]
        all_ret_series.append(rets)
        codes.append(h.fund_code)

    # Align to min length
    min_len = min(len(r) for r in all_ret_series)
    ret_matrix = np.array([r[-min_len:] for r in all_ret_series])

    annual_ret = np.mean(ret_matrix, axis=1) * 252
    cov_matrix = np.cov(ret_matrix) * 252

    # Current weights (from active funds only)
    total_active_mv = sum(h.current_mv for h in active)
    current_weights = np.array([h.current_mv / total_active_mv for h in active])

    # Monte Carlo
    np.random.seed(42)
    results = np.zeros((num_portfolios, 3))  # [return, vol, sharpe]

    all_weights = np.random.dirichlet(np.ones(num_assets), num_portfolios)

    for i in range(num_portfolios):
        w = all_weights[i]
        port_ret = np.dot(w, annual_ret)
        port_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))
        port_sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0
        results[i] = [port_ret, port_vol, port_sharpe]

    # Optimal portfolios
    max_sharpe_idx = int(np.argmax(results[:, 2]))
    min_vol_idx = int(np.argmin(results[:, 1]))

    ef.optimal_sharpe_weights = {
        codes[i]: round(float(all_weights[max_sharpe_idx][i]), 4)
        for i in range(num_assets)
    }

    ef.min_vol_weights = {
        codes[i]: round(float(all_weights[min_vol_idx][i]), 4)
        for i in range(num_assets)
    }

    # Current position on frontier
    current_ret = float(np.dot(current_weights, annual_ret))
    current_vol = float(np.sqrt(np.dot(current_weights.T, np.dot(cov_matrix, current_weights))))

    ef.current_position_return = round(current_ret * 100, 2)
    ef.current_position_risk = round(current_vol * 100, 2)

    # Distance to frontier: find the point on frontier with same volatility
    # (how much extra return could we get at same risk?)
    vol_target = current_vol
    frontier_max_ret = 0
    for i in range(num_portfolios):
        if abs(results[i, 1] - vol_target) / vol_target < 0.05:  # within 5% vol
            frontier_max_ret = max(frontier_max_ret, results[i, 0])

    if frontier_max_ret > 0:
        ef.distance_to_frontier_pct = round(float((frontier_max_ret - current_ret) * 100), 2)
    else:
        ef.distance_to_frontier_pct = 0.0

    # Position quality
    if current_vol <= 0:
        ef.position_quality = "unknown"
    else:
        current_sharpe = (current_ret - risk_free_rate) / current_vol
        max_sharpe = results[max_sharpe_idx, 2]
        if max_sharpe > 0 and current_sharpe / max_sharpe > 0.9:
            ef.position_quality = "optimal"
        elif current_sharpe / max_sharpe > 0.7:
            ef.position_quality = "near_optimal"
        elif current_sharpe / max_sharpe > 0.4:
            ef.position_quality = "suboptimal"
        else:
            ef.position_quality = "poor"

    return ef
