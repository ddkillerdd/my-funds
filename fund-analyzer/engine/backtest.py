"""Pure backtest evaluation logic for fund advice (RFC-012).

Independent, side-effect-free: given the fund's and benchmark's NAV at advice time
and at validation time, decide whether the directional advice (REDUCE / INCREASE)
was a hit / miss / neutral. HOLD / WATCH are returned as neutral (no directional bet).

Design:
  - Relative return vs benchmark beats absolute move (avoids "down with the whole
    market looks correct" illusion). This is what "create excess value" means.
  - Only directional actions (REDUCE / INCREASE) count toward hit-rate.
  - Comparison uses close NAV series, annualized-neutral over the window.

All functions are pure; persistence/hooks live in the integration layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from decimal import Decimal
from typing import Optional


# Actions that carry a directional bet and thus participate in hit-rate.
DIRECTIONAL_ACTIONS = ("reduce", "increase")
# Hedge threshold: relative return within +/- this fraction is treated as neutral
# (not enough signal to call it a clear hit or miss).
NEUTRAL_BAND = Decimal("0.005")  # 0.5%


@dataclass
class Verdict:
    verdict: str          # hit / miss / neutral
    fund_change_pct: Optional[Decimal]
    benchmark_change_pct: Optional[Decimal]
    relative_return: Optional[Decimal]  # fund - benchmark
    reason: str


def _pct(before: Decimal, after: Decimal) -> Optional[Decimal]:
    """Percent change from before->after, as Decimal, or None if invalid."""
    if before is None or after is None:
        return None
    before = Decimal(before)
    after = Decimal(after)
    if before <= 0:
        return None
    return (after / before - Decimal(1))


def validate_advice(
    action: str,
    nav_before: Optional[Decimal],
    nav_after: Optional[Decimal],
    benchmark_before: Optional[Decimal],
    benchmark_after: Optional[Decimal],
    neutral_band: Decimal = NEUTRAL_BAND,
) -> Verdict:
    """Judge one advice against observed NAV movement (RFC-012 §5.1).

    Args:
        action: 'reduce' | 'increase' | 'hold' | 'watch'
        nav_before / nav_after: fund unit NAV at advice time / validation time
        benchmark_before / benchmark_after: benchmark (e.g. 沪深300) index NAV
        neutral_band: relative-return band that maps to neutral

    Returns:
        Verdict with normalized verdict in {hit, miss, neutral}.
    """
    action = (action or "").strip().lower()

    # Non-directional or missing data -> neutral (no bet, nothing to judge).
    if action not in DIRECTIONAL_ACTIONS:
        return Verdict("neutral", None, None, None, f"action '{action}' is not directional")

    fund_chg = _pct(nav_before, nav_after)
    bench_chg = _pct(benchmark_before, benchmark_after)
    if fund_chg is None:
        return Verdict("neutral", fund_chg, bench_chg, None, "missing fund NAV")

    if bench_chg is not None:
        rel = fund_chg - bench_chg
    else:
        # No benchmark available -> fall back to fund alone but flag it.
        rel = fund_chg
        bench_chg = Decimal("0")

    # Direction logic:
    #   REDUCE  : bet that fund underperforms -> relative < 0 is a hit
    #   INCREASE: bet that fund outperforms   -> relative > 0 is a hit
    if action == "reduce":
        hit_when = rel < -neutral_band
        miss_when = rel > neutral_band
    else:  # increase
        hit_when = rel > neutral_band
        miss_when = rel < -neutral_band

    if hit_when:
        v, reason = "hit", "relative return favored the bet"
    elif miss_when:
        v, reason = "miss", "relative return went against the bet"
    else:
        v, reason = "neutral", "relative return within neutral band"

    return Verdict(v, fund_chg, bench_chg, rel, reason)


def summarize(verdicts: list[Verdict]) -> dict:
    """Aggregate a list of verdicts into hit-rate stats (RFC-012 §5)."""
    directional = [v for v in verdicts if v.verdict in ("hit", "miss")]
    hits = sum(1 for v in verdicts if v.verdict == "hit")
    miss = sum(1 for v in verdicts if v.verdict == "miss")
    total = len(verdicts)
    dir_total = len(directional)
    return {
        "total": total,
        "directional": dir_total,
        "hits": hits,
        "miss": miss,
        "neutral": total - hits - miss,
        "hit_rate": round(hits / dir_total, 4) if dir_total else None,
    }


def sample_hit_rate(
    factor: str,
    history: list[tuple[str, str]],
    recent_n: Optional[int] = None,
) -> dict:
    """Compute per-factor / per-action-type hit rate for online learning (RFC-012 §7).

    Args:
        factor: a dimension label, e.g. 'trend', 'sharpe' (informational)
        history: list of (action, verdict) pairs, oldest first
        recent_n: rolling window; if set, only the last N entries count

    Returns:
        {factor, total, hits, miss, hit_rate, window}
    """
    entries = history
    if recent_n is not None and recent_n > 0:
        entries = history[-recent_n:]
    verdicts = [Verdict(v, None, None, None, factor) for _, v in entries if v in ("hit", "miss")]
    s = summarize(verdicts)
    s["factor"] = factor
    s["window"] = recent_n
    s["sample_count"] = len(entries)
    return s
