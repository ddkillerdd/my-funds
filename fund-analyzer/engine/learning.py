"""Adaptive on-line learning: map observed hit-rates to calibrated confidence and
view weights for the interpretation layer (RFC-012 §5.2, §7).

Guiding rules:
  - Factor layer (Sharpe/drawdown/MACD ...) is NEVER touched. We only calibrate the
    decision/interpretation layer (confidence, emphasis).
  - Anti-overfitting:
      1. Minimum sample threshold: with too few samples we shrink toward a default,
         never over-confident.
      2. Rolling window: recent N judgements only (old data decay).
      3. Smoothing (Bayesian-ish shrinkage toward a prior) instead of jumping 0/1.

All functions are pure; persistence lives in the integration layer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional


# Default confidence applied when we have no evidence (shrink target).
DEFAULT_CONFIDENCE = Decimal("0.6")
# Minimum directional samples before we start trusting observed hit-rate.
MIN_SAMPLES = 5
# Trusted sample count where observed hit-rate is weighted ~ (n/(n+prior_weight)).
PRIOR_WEIGHT = 10
# Floor/ceil for calibrated confidence.
CONF_MIN = Decimal("0.40")
CONF_MAX = Decimal("0.95")


def _clamp(x: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, x))


def calibrate_confidence(
    hit_rate: Optional[float],
    sample_count: int,
    default_conf: Decimal = DEFAULT_CONFIDENCE,
) -> Decimal:
    """Map an observed hit-rate to a calibrated confidence for the decision layer.

    Anti-overfitting: with sample_count below MIN_SAMPLES, we heavily shrink toward
    default_conf; as samples grow we trust hit_rate more (Bayesian shrinkage).

    Args:
        hit_rate: fraction of directional bets that hit (0..1) or None
        sample_count: number of directional samples

    Returns:
        Decimal confidence in [CONF_MIN, CONF_MAX]
    """
    if hit_rate is None or sample_count < MIN_SAMPLES:
        # Not enough evidence -> stay conservative, don't over-claim.
        return default_conf

    hit_rate = float(hit_rate)
    # Shrink observed hit-rate toward default_conf's neutral value (0.5) with
    # strength proportional to evidence vs prior.
    alpha = sample_count / (sample_count + PRIOR_WEIGHT)
    smoothed = alpha * hit_rate + (1 - alpha) * 0.5
    # Center on default when uncertain; push toward smoothed as evidence grows.
    conf = float(default_conf) + (smoothed - 0.5) * alpha
    return _clamp(Decimal(str(round(conf, 4))), CONF_MIN, CONF_MAX)


def view_weight_adjustment(
    hit_rates: dict[str, Optional[float]],
    sample_counts: dict[str, int],
) -> dict[str, dict]:
    """Derive emphasis weights per interpretive view from historical hit-rates.

    Args:
        hit_rates: view key -> observed hit-rate (or None)
        sample_counts: view key -> directional sample count

    Returns:
        {view: {weight, reliable, emphasis}} where:
          - weight: 0..1 how strongly this view should be emphasized relative to others
          - reliable: True if enough samples to trust
          - emphasis: 'strong' | 'normal' | 'soft' human-readable
    """
    out: dict[str, dict] = {}
    # Filter to views with enough evidence.
    reliable = {
        k: (hit_rates.get(k) is not None and sample_counts.get(k, 0) >= MIN_SAMPLES)
        for k in set(hit_rates) | set(sample_counts)
    }
    weights: dict[str, float] = {}
    for k in reliable:
        if reliable[k]:
            weights[k] = calibrate_confidence(hit_rates[k], sample_counts[k], DEFAULT_CONFIDENCE)
        else:
            weights[k] = DEFAULT_CONFIDENCE

    total = sum(weights.values()) or 1.0
    for k in reliable:
        w = weights[k] / total if total else 1.0
        hr = hit_rates.get(k)
        if hr is None:
            emphasis = "normal"
        elif hr >= 0.65:
            emphasis = "strong"
        elif hr <= 0.40:
            emphasis = "soft"
        else:
            emphasis = "normal"
        out[k] = {
            "weight": round(w, 4),
            "reliable": bool(reliable[k]),
            "emphasis": emphasis,
            "hit_rate": round(hr, 4) if hr is not None else None,
            "samples": sample_counts.get(k, 0),
        }
    return out


def build_feedback_prompt(
    view_feedback: dict[str, dict],
    action_hit_rates: Optional[dict] = None,
) -> str:
    """Render online-learning feedback into a hint for the interpretation layer.

    This is appended to LLM prompts so the report can reflect historically
    more-accurate views (RFC-012 §7). Confidence numbers come from calibrate_confidence.
    """
    lines: list[str] = []
    strong = [k for k, v in view_feedback.items() if v.get("emphasis") == "strong"]
    soft = [k for k, v in view_feedback.items() if v.get("emphasis") == "soft"]
    parts = []
    if strong:
        parts.append("历史上命中率较高的视角：" + "、".join(sorted(strong)))
    if soft:
        parts.append("历史上有效性较弱的视角（建议谨慎）：" + "、".join(sorted(soft)))
    if action_hit_rates:
        a_parts = [
            f"{a}({round(float(hr)*100)}%)" for a, hr in action_hit_rates.items()
            if hr is not None
        ]
        if a_parts:
            action_phr = "、".join(a_parts)
            if strong or soft:
                parts.append("对应的调仓动作历史命中率：" + action_phr)
            else:
                parts.append("历史回测中，调仓动作命中率：" + action_phr)
    if parts:
        lines.append("[在线学习反馈] " + "；".join(parts) + "。请据此校准你的置信度与表述重点。")
    return "\n".join(lines)
