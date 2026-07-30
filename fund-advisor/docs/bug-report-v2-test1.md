# Bug Report: v2.0.0 首次测试记录

## 测试时间
2026-07-30 14:04-14:08

## 测试结果
❌ **首次测试失败** (HTTP 500)

## 发现的问题

### Bug 1: `facts_computer.py` 降级结果缺少 `health_score` 字段

**位置**: `advisor_service.py` `_fund_fallback()`
**现象**: step-3.7-flash 返回的非标准 JSON（被截断/空）导致 `_parse_json()` 失败，进入降级。
降级函数 `_fund_fallback()` 返回的 dict 里缺少 `health_score` 字段，
导致 Step2 `_step2_synthesis()` 在 `f"健康度 {fa['health_score']}/100"` 处 KeyError。

**根因**:
1. step-3.7-flash 的 JSON 偶有截断/空值（temperature=0.1 + max_tokens=2048 时也有发生）
2. `_fund_fallback()` 返回的 dict 和正常的 `_parse_json()` 返回的 dict 结构不一致

**修复方案**:
- `_fund_fallback()` 补齐所有 `_step2_synthesis()` 需要的字段

### Bug 2: `long_return_pct` 字段不存在于所有趋势返回

**位置**: `facts_computer.py` `_compute_trend_signals()` 返回的 dict
**现象**: 数据不足时（<5 条快照），返回 `{"state": "数据不足", "signals": [], "num_snapshots": ...}`
不包含 `long_return_pct`。但 `_step2_synthesis()` 直接用 `facts['trend']['long_return_pct']` 格式化。

**修复方案**:
- 所有趋势返回添加所有必需字段的默认值（`long_return_pct`, `short_trend_pct`, `volatility_pct` 等）

### Bug 3: Step1 JSON 解析率偏低

**现象**: 4 只基金中 2 只解析成功，2 只进入降级（解析率 50%）
原因:
- 000311: JSON 字符串被截断 (Unterminated string)
- 161725: 返回为空 (Expecting value)

**根因分析**:
step-3.7-flash 在 temperature=0.1 时仍有截断风险。NVIDIA NIM 的免费 tier 也有偶发不稳定性。

**修复方案**:
- 增加 max_tokens 到 4096
- 降级结果补充完整字段
- 考虑是否对 step-3.7 改用 temperature=0（可能减少截断）

## 文档

修复记录更新到:
- `docs/RFC-003-multi-agent-analysis.md` - 测试结果附录
- `DEVLOG.md` - Bug 修复记录
- 代码注释
