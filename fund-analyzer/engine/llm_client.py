"""
LLM Client for FundAnalyzer

Encapsulates API calls to NewAPI gateway with:
- Fallback chain: nemotron-nano → deepseek-v4-flash → pure-calculation
- Rate-limit-safe serial calls
- JSON parsing with validation
- Timeout/retry logic
"""

from __future__ import annotations
import json
import re
import time
import logging
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)


class LLMConfig:
    """LLM API configuration with multi-model support."""

    def __init__(
        self,
        api_base: str,
        api_key: str,
        primary_model: str = "nvidia/nvidia-nemotron-nano-9b-v2",
        fallback_models: Optional[List[str]] = None,
        default_timeout: float = 60.0,
        fallback_timeout: float = 90.0,
        max_retries_per_model: int = 1,
        # --- v5: 按角色分配模型 ---
        model_assignments: Optional[Dict[str, str]] = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.primary_model = primary_model
        self.fallback_models = fallback_models or [
            "deepseek-ai/deepseek-v4-flash",
        ]
        self.default_timeout = default_timeout
        self.fallback_timeout = fallback_timeout
        self.max_retries_per_model = max_retries_per_model
        # 按步骤/视角指定的模型（优先于 primary_model）
        self.model_assignments = model_assignments or {}


class LLMClient:
    """Thin wrapper around OpenAI-compatible chat completions API."""

    def __init__(self, config: LLMConfig, http_client: Optional[httpx.Client] = None):
        self.config = config
        self._http = http_client or httpx.Client(timeout=config.default_timeout)
        self._call_count = 0
        self._failure_count = 0
        self._fallback_count = 0
        self._models_used: Dict[str, str] = {}

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def fallback_count(self) -> int:
        return self._fallback_count

    @property
    def models_used(self) -> Dict[str, str]:
        return self._models_used.copy()

    def call(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: Optional[float] = None,
        step_label: str = "",
        model: Optional[str] = None,  # v5: override model per call
    ) -> str:
        """
        Call LLM with fallback chain.

        If `model` is given, it overrides the primary and becomes
        the only model tried (no fallback — caller should handle retry).
        If `model` is None, the full primary→fallback chain is used.

        Returns:
            Raw response text.

        Raises:
            RuntimeError if ALL models fail.
        """
        self._call_count += 1

        if model:
            models_to_try = [model]
        else:
            models_to_try = [self.config.primary_model] + [
                m for m in self.config.fallback_models if m != self.config.primary_model
            ]

        last_error = None

        for i, model in enumerate(models_to_try):
            is_fallback = i > 0
            t = timeout or (
                self.config.fallback_timeout if is_fallback else self.config.default_timeout
            )

            for attempt in range(self.config.max_retries_per_model + 1):
                try:
                    result = self._call_once(model, prompt, temperature, max_tokens, t)
                    if is_fallback:
                        self._fallback_count += 1
                    self._models_used[step_label or f"call_{self._call_count}"] = model
                    return result
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"[{step_label}] model={model} attempt={attempt+1} failed: {e}"
                    )
                    if attempt < self.config.max_retries_per_model:
                        time.sleep(2)

        self._failure_count += 1
        raise RuntimeError(
            f"LLM call failed after trying all models ({len(models_to_try)}). "
            f"Last error: {last_error}"
        )

    def _call_once(
        self,
        model: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """Single API call."""
        url = f"{self.config.api_base}/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        start = time.time()
        response = self._http.post(url, json=payload, headers=headers, timeout=timeout)
        elapsed = time.time() - start

        if response.status_code != 200:
            raise RuntimeError(
                f"API returned {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        logger.info(
            f"[{self._call_count}] model={model} temp={temperature} "
            f"tokens={max_tokens} elapsed={elapsed:.1f}s"
        )

        # Extract content
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices in response: {json.dumps(data)[:300]}")

        message = choices[0].get("message", {})
        content = message.get("content")

        if content is None:
            # NIM reasoning models put content in reasoning field
            reasoning = message.get("reasoning")
            if reasoning:
                content = reasoning
            else:
                raise RuntimeError(f"No content or reasoning in message: {json.dumps(message)[:300]}")

        return content.strip()


def parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from LLM response.
    Handles:
    - Pure JSON
    - JSON inside ```json ... ```
    - JSON inside ``` ... ```
    - JSON with trailing text
    Ensures the returned value is a dict (LLM sometimes returns a top-level array;
    in that case we take the first dict element so callers can safely .get()).
    """

    def _coerce(value):
        # JSON string double-wrap
        if isinstance(value, str):
            try:
                return _coerce(json.loads(value))
            except (json.JSONDecodeError, TypeError):
                return None
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            # LLM sometimes wraps the object in an array: [{...}] → take first dict
            for item in value:
                if isinstance(item, dict):
                    return item
                if isinstance(item, str):
                    try:
                        d = json.loads(item)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(d, dict):
                        return d
            return None
        return None

    if not raw:
        return None

    # Try pure JSON first
    try:
        return _coerce(json.loads(raw))
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json blocks
    patterns = [
        r"```json\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, raw)
        for match in matches:
            try:
                return _coerce(json.loads(match))
            except json.JSONDecodeError:
                continue

    # Try finding JSON object boundaries (multiple candidates, pick best)
    best_result = None
    best_key_count = -1
    
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_pos = 0
        while True:
            start = raw.find(start_char, start_pos)
            if start < 0:
                break
            depth = 0
            end_pos = -1
            for i in range(start, len(raw)):
                ch = raw[i]
                if ch == start_char:
                    depth += 1
                elif ch == end_char:
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break
            if end_pos < 0:
                break
            try:
                candidate = json.loads(raw[start:end_pos])
                # Handle double-wrapped JSON strings
                if isinstance(candidate, str):
                    try:
                        candidate = json.loads(candidate)
                    except (json.JSONDecodeError, TypeError):
                        pass
                if isinstance(candidate, dict):
                    key_count = len(candidate)
                    if key_count > best_key_count:
                        best_result = candidate
                        best_key_count = key_count
                elif isinstance(candidate, list) and best_key_count < 0:
                    best_result = candidate
                    best_key_count = 0
            except json.JSONDecodeError:
                pass
            start_pos = end_pos  # move past this candidate, try next
    
    if best_result is not None:
        logger.info(f"Extracted JSON with {best_key_count} top-level keys from response (non-pure JSON)")
        return _coerce(best_result)

    logger.warning(f"Failed to parse JSON from response: {raw[:200]}...")
    return None


def validate_diagnosis_json(data: Dict[str, Any], schema_name: str = "unknown") -> List[str]:
    """
    Validate that a parsed JSON dict has the required structure for a diagnosis.
    Returns list of missing fields (empty = valid).
    """
    errors = []

    # Common fields for view diagnoses
    if schema_name in ("trend", "risk", "value", "technical"):
        for field in ("overall_score", "diagnosis", "key_risk", "key_opportunity", "confidence"):
            if field not in data and field != f"overall_{schema_name}_score":
                pass  # will check aliases

        if "diagnosis" not in data:
            errors.append(f"{schema_name}: missing 'diagnosis' field")
        elif not isinstance(data["diagnosis"], list):
            errors.append(f"{schema_name}: 'diagnosis' is not a list")
        elif len(data["diagnosis"]) == 0:
            errors.append(f"{schema_name}: 'diagnosis' is empty")

        for field in ("confidence",):
            if field in data and not isinstance(data[field], (int, float)):
                errors.append(f"{schema_name}: '{field}' is not numeric")

    elif schema_name == "debate":
        for field in ("contradictions", "consensus_level", "health_score", "strengths", "risks", "action", "confidence"):
            if field not in data:
                errors.append(f"debate: missing '{field}'")

    elif schema_name == "portfolio":
        for field in ("overall_health_score", "concentration_risk", "correlation_issues", "strengths", "weaknesses"):
            if field not in data:
                errors.append(f"portfolio: missing '{field}'")

    return errors


# ============================================================
#  PURE CALCULATION FALLBACK
# ============================================================

def fallback_trend_diagnosis(qi) -> Dict[str, Any]:
    """Generate trend diagnosis from quant indicators alone (no LLM)."""
    t = qi.trend
    score = t.trend_strength or 50
    return {
        "overall_trend_score": score,
        "trend_direction": t.trend_direction,
        "trend_strength_label": (
            "强势" if score >= 70 else "偏强" if score >= 55 else
            "中性" if score >= 45 else "偏弱" if score >= 30 else "弱势"
        ),
        "diagnosis": [
            {
                "claim": f"净值{t.current_nav:.4f}处于区间" + (
                    "上方,趋势偏强" if t.trend_direction == "up" else "中部,方向不明确"
                ),
                "confidence": 0.6,
                "evidence": f"(净值={t.current_nav:.4f}, MA20={t.ma20})",
                "sentiment": "positive" if t.trend_direction == "up" else "neutral",
            }
        ],
        "key_risk": "降级分析 — 基于纯量化指标推断",
        "key_opportunity": "",
        "confidence": 0.4,
        "uncertainties": ["LLM调用失败, 使用降级分析"],
    }


def fallback_risk_diagnosis(qi) -> Dict[str, Any]:
    r = qi.risk
    vol = r.annual_volatility_pct or 20
    score = max(0, 100 - int(vol * 2))
    return {
        "overall_risk_score": score,
        "risk_level": r.volatility_regime,
        "diagnosis": [
            {
                "claim": f"年化波动率{vol}%，处于{r.volatility_regime}风险区间",
                "confidence": 0.7,
                "evidence": f"(年化波动率={vol}%)",
                "sentiment": "negative" if vol > 20 else "neutral",
            }
        ],
        "key_risk": "降级分析 — 基于纯量化指标推断",
        "key_opportunity": "",
        "confidence": 0.4,
        "uncertainties": ["LLM调用失败, 使用降级分析"],
    }


def fallback_value_diagnosis(qi) -> Dict[str, Any]:
    e = qi.efficiency
    sharpe = e.sharpe_ratio or 0
    score = int(min(100, sharpe * 50))
    return {
        "overall_value_score": score,
        "diagnosis": [
            {
                "claim": f"Sharpe {sharpe:.2f}，" + ("性价比可接受" if sharpe > 0.5 else "性价比偏低"),
                "confidence": 0.6,
                "evidence": f"(Sharpe={sharpe:.2f})",
                "sentiment": "positive" if sharpe > 1 else "neutral" if sharpe > 0.5 else "negative",
            }
        ],
        "key_risk": "降级分析 — 基于纯量化指标推断",
        "key_opportunity": "",
        "confidence": 0.4,
        "uncertainties": ["LLM调用失败, 使用降级分析"],
    }


def fallback_technical_diagnosis(qi) -> Dict[str, Any]:
    mo = qi.momentum
    rsi = mo.rsi_14 or 50
    if rsi > 60:
        score = 70
    elif rsi < 40:
        score = 30
    else:
        score = 50
    return {
        "overall_tech_score": score,
        "diagnosis": [
            {
                "claim": f"RSI={rsi}，{mo.rsi_signal}信号",
                "confidence": 0.6,
                "evidence": f"(RSI14={rsi})",
                "sentiment": "positive" if rsi > 55 else "negative" if rsi < 45 else "neutral",
            }
        ],
        "key_risk": "降级分析 — 基于纯量化指标推断",
        "key_opportunity": "",
        "confidence": 0.4,
        "uncertainties": ["LLM调用失败, 使用降级分析"],
    }


def fallback_debate(qi, trend, risk, value, technical) -> Dict[str, Any]:
    """
    Fallback debate with quantitative decision rules (RFC-006 方案B).

    Ensures LLM-down still produces differentiated, actionable suggestions
    instead of a blanket "hold" for every fund.
    """
    scores = [
        trend.get("overall_trend_score", 50) if isinstance(trend, dict) else 50,
        risk.get("overall_risk_score", 50) if isinstance(risk, dict) else 50,
        value.get("overall_value_score", 50) if isinstance(value, dict) else 50,
        technical.get("overall_tech_score", 50) if isinstance(technical, dict) else 50,
    ]
    risk_norm = 100 - scores[1]
    avg = int((scores[0] + risk_norm + scores[2] + scores[3]) / 4)

    # Read key quantitative indicators (ground truth)
    sharpe = qi.efficiency.sharpe_ratio if qi.efficiency and qi.efficiency.sharpe_ratio is not None else 0
    sortino = qi.efficiency.sortino_ratio if qi.efficiency and qi.efficiency.sortino_ratio is not None else 0
    current_dd = abs(qi.risk.current_drawdown_pct or 0) if qi.risk else 0
    max_dd = abs(qi.risk.max_drawdown_pct or 0) if qi.risk else 0
    vol = qi.risk.annual_volatility_pct or 0 if qi.risk else 0
    macd_signal = qi.macd.signal or "unknown" if qi.macd else "unknown"
    trend_dir = qi.trend.trend_direction or "unknown" if qi.trend else "unknown"

    # --- Quantitative decision (RFC-006 decision matrix) ---
    # 风险三要素：回撤是否已释放 / 趋势方向 / Sharpe 是否极端负值
    dd_released = max_dd > 0 and current_dd < max_dd * 0.5  # 回撤已大幅释放
    trend_up = trend_dir == "up"
    trend_down = trend_dir == "down"
    sharp_drop = sharpe < -0.5  # 极端负收益
    overbought_risk = vol > 60  # 极端高波动(如单日涨跌幅大)时谨慎加仓

    conditions = []
    if avg < 30 or current_dd > 30 or sharp_drop:
        action_type = "sell"
        change = -50 if current_dd > 30 else -30
        reasoning = f"健康分{avg}+回撤{current_dd:.1f}%+Sharpe{sharpe:.2f}触发清仓线"
        conditions.append("净值跌破MA60 → 全部清仓")
    elif avg < 55 or sharpe < 0:
        # 默认减仓，但若“风险已释放 + 趋势向好”且仅Sharpe略低，不误砍 → hold
        if dd_released and (trend_up or macd_signal == "golden_cross_active"):
            action_type = "hold"
            change = 0
            reasoning = (f"回撤已释放({current_dd:.1f}%)+趋势向好，Sharpe{sharpe:.2f}略低但风险可控，"
                         f"建议持有而非减仓")
            conditions.append("MACD柱 < -0.005 → 转为reduce")
            conditions.append("Sharpe连续2月<0 且趋势转down → 再评估减仓")
        else:
            action_type = "reduce"
            change = -20 if sharpe < 0 else -10
            reasoning = f"Sharpe{sharpe:.2f}偏低，减仓{abs(change)}%控制风险"
            conditions.append("MACD柱 < -0.005 → 追加减仓5%")
            conditions.append(f"当前回撤 > -{max_dd * 0.6:.0f}% → 转为sell")
    elif avg > 75 and sharpe > 1.0 and trend_up:
        action_type = "add"
        change = 10 if not overbought_risk else 0
        reasoning = (f"健康分{avg}+Sharpe{sharpe:.2f}三优信号，建议增持10%"
                     if not overbought_risk else
                     f"健康分{avg}+Sharpe{sharpe:.2f}良好但波动率{vol:.0f}%偏高，暂观望")
        conditions.append("Sharpe连续2月>1.5 → 再增持5%")
    elif macd_signal == "death_cross_active" or trend_down:
        action_type = "watch"
        change = 0
        reasoning = "趋势走弱/MACD死叉，暂持但需监控"
        conditions.append("MACD柱 > 0.005 且持续3日 → 转为hold")
        conditions.append("RSI < 30 → 触发减仓10%")
    else:
        action_type = "hold"
        change = 0
        reasoning = "信号混合，维持当前仓位"
        conditions.append("MACD柱 < -0.005 → 转为reduce")

    # --- Quantitative strengths/risks ---
    risks = []
    if vol > 30:
        risks.append(f"年化波动率{vol:.1f}%属于高风险水平")
    if current_dd > 10:
        risks.append(f"当前回撤{current_dd:.1f}%仍然显著")
    if sharpe < 0.5:
        risks.append(f"Sharpe {sharpe:.2f}低于1.0，风险调整收益不佳")
    if macd_signal == "death_cross_active":
        risks.append("MACD死亡交叉，动能减弱")

    strengths = []
    if sharpe > 1.0:
        strengths.append(f"Sharpe {sharpe:.2f} > 1.0，风险调整收益优秀")
    if sortino > 1.0:
        strengths.append(f"Sortino {sortino:.2f} > 1.0，下行风险控制良好")
    if trend_dir == "up":
        strengths.append("趋势方向向上，均线系统支撑")
    if max_dd > 0 and current_dd < max_dd * 0.5:
        strengths.append(f"当前回撤{current_dd:.1f}%远低于历史最大{max_dd:.1f}%，风险已释放")

    return {
        "contradictions": [],
        "consensus_level": 0.5,
        "consensus_label": "partial_disagreement",
        "health_score": avg,
        "health_label": (
            "良好" if avg >= 70 else "中等偏上" if avg >= 55 else
            "中等" if avg >= 40 else "中等偏下" if avg >= 25 else "较差"
        ),
        "strengths": strengths,
        "risks": risks,
        "action": {
            "type": action_type,
            "confidence": 0.45,
            "reasoning": reasoning,
            "change_pct": change,
            "trigger_conditions": conditions,
            "target_ratio_pct": None,
        },
        "confidence": 0.35,
        "uncertainties": ["LLM调用失败, 使用降级分析(含量化决策)"],
    }


# ============================================================
#  ACTION NORMALIZATION (RFC-006 方案A 后处理校验)
# ============================================================

def normalize_action(action) -> Dict[str, Any]:
    """
    Ensure an action (dict or absent) always contains the RFC-006 fields:
    type / confidence / reasoning / change_pct / trigger_conditions / target_ratio_pct.

    Acts as a safety net when the LLM omits the new fields, preserving
    backward compatibility with old dict-based reports in the DB.
    """
    if isinstance(action, dict):
        act = dict(action)
    else:
        act = {}

    act.setdefault("type", "hold")
    act.setdefault("confidence", 0.5)
    act.setdefault("reasoning", "")
    if "change_pct" not in act or act["change_pct"] is None:
        act["change_pct"] = 0.0
    act["trigger_conditions"] = act.get("trigger_conditions") or []
    if "target_ratio_pct" not in act:
        act["target_ratio_pct"] = None

    # Sanity: change_pct sign must match action type
    t = act["type"]
    cp = float(act["change_pct"] or 0.0)
    if t in ("buy", "add") and cp < 0:
        act["change_pct"] = abs(cp)
    elif t in ("reduce", "sell") and cp > 0:
        act["change_pct"] = -abs(cp)
    elif t in ("hold", "watch"):
        act["change_pct"] = 0.0

    return act
