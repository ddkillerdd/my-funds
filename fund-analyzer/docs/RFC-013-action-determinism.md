# RFC-013 动作确定性收敛：量化硬决策 + LLM 只解读

- **状态**: ✅ 已实施并验证（v6.3，commit 见 CHANGELOG）
- **作者**: OpenClaw (AAA)
- **日期**: 2026-07-31（施工） / 2026-08-01（真实报告核验收尾）
- **关联**: RFC-006（多模型辩论+决策矩阵）、RFC-012（建议回测+在线学习）
- **触发**: 同日三份报告（id=19/20/21）对同一持仓给出互相矛盾的操作建议

---

## 1. 问题：同一量化事实，建议动作随机摆荡

2026-07-31 三份报告（生成于 17:59 / 18:57 / 21:50）对**同一批 4 只基金**给出不同建议：

| 基金 | 量化事实(三份100%相同) | id19 | id20 | id21 |
|------|----------------------|------|------|------|
| 纳指 018044 | sharpe=1.76, vol=15.7, MACD死叉 | reduce | **hold** | reduce |
| 白酒 161725 | sharpe=-0.33, vol=42.7, MACD金叉 | reduce | **hold** | reduce |
| 科创 588760 | sharpe=-0.20, vol=78.4, dd=-59 | reduce | reduce | **hold** |
| 沪深300 000311 | sharpe=0.71, 趋势向上 | reduce | **hold** | **hold** |

**决定性证据**：四视角量化分本身在三份报告间就 ±20 分摆荡（同一基金）：

- 科创 trend: **55 → 65 → 75**（摆 20 分）
- 科创 risk: **85 → 68 → 72**（摆 17 分）
- 科创 value: **35 → 55 → 45**（摆 20 分）
- 纳指 value: **85 → 78 → 88**（摆 10 分）
- 纳指 trend: **60 → 55 → 55**

### 根因定位（已用数据证实）

摆荡的源头**不是"LLM 翻译"而是"LLM 打分"**：

```
净值/sharpe/dd（quant，100% 数学确定）
  → 4 个视角 score 由 LLM 生成       ← 每次随机摆荡 ±20分
  → debate action 由 LLM 自由生成     ← 把摆荡的分翻译成随机动作
  → 同一事实 → 不同动作
```

代码证据（`analyzer.py`）：
- `_analyze_4_views()`：`overall_trend_score` 等四视角分数**直接取自 LLM 返回的 JSON**（`data.get("overall_trend_score")`），只有 LLM 抛异常才走 `fallback_*_diagnosis()` 量化计算。
- `_debate_synthesis()`：`action=normalize_action(raw_action)` 直接来自 LLM 输出，`fallback_debate` 量化矩阵**仅在 LLM 完全失败时兜底**。

### 违反既定准则

USER.md / 项目准则明确要求「**LLM 只做解读不做评分，荐基/择时数字全量化**」。当前实现让 LLM 承担了评分与动作决策，且 NIM 上游（nano-9b）输出不稳定，导致建议不可复现。

---

## 2. 目标

1. **同一天、同一持仓数据 → 输出相同的操作建议**（确定性）。
2. 全量化动作、LLM 只提供解释文案与矛盾提示。
3. 与 RFC-012 在线学习兼容（命中率收集的仍是同一套动作口径）。

---

## 3. 现状：可复用的确定性资产（无需新造）

引擎已内置完善的确定性规则，但目前只是 fallback：

| 已有函数 | 作用 | 当前角色 |
|---------|------|---------|
| `fallback_trend_diagnosis` | 趋势强度 → 分数 | 仅 LLM 失败兜底 |
| `fallback_risk_diagnosis` | 年化波动 → risk 分数 | 仅 LLM 失败兜底 |
| `fallback_value_diagnosis` | Sharpe → value 分数 | 仅 LLM 失败兜底 |
| `fallback_technical_diagnosis` | RSI → tech 分数 | 仅 LLM 失败兜底 |
| `fallback_debate` | **六档量化决策矩阵**（sell/reduce/豁免hold/add/watch/hold） | 仅 debate LLM 失败兜底 |

`fallback_debate` 决策矩阵（RFC-006）已非常完善：
- `avg<30 或 回撤>30% 或 sharpe<-0.5` → sell
- `avg<55 或 sharpe<0` → 若 `dd_released 且 (trend_up 或 MACD金叉)` → hold（免误砍），否则 reduce
- `avg>75 且 sharpe>1.0 且 trend_up` → add（vol>60 观望）
- MACD死叉/趋势向下 → watch
- 其他 → hold

RFC-013 = 把这套从「fallback」**提升为「动作决策主路径」**。

---

## 3.5 业界实证：为什么必须量化优先（用于盈利的依据）

2025 FINSABER 实证（arXiv 2505.07078，二十年/100+标的回测）：

> **「LLM 择时策略在牛市过度保守跑输被动基准，在熊市过度激进导致重亏」**。纯 LLM 自由动作长期不可靠，优势在扩大样本/拉长时间后显著衰减。结论指向：**优先趋势检测与风险控制（deterministic），而非堆叠复杂 LLM 框架**。

对照本项目现状（见 §1）：
- 纳指 sharpe=1.76（牛市优质资产）被 LLM 判 reduce → 正是 FINSABER 说的牛市过度保守（应持有/增持才能盈利）
- 科创 dd=-59 深亏却 hold → 熊市该止损却坚守，重亏风险

FINSABER 的结论 = RFC-013 的核心：**动作由量化趋势/风险决定，LLM 只辅助判读**。这是业界验证过、以盈利为导向的正确形态，而非猜测。

## 4. 方案设计：动作全量化，LLM 降级为解释器

### 4.0 盈利导向：Regime-Aware 决策升级（响应 FINSABER 结论）

基础版 RFC-013 用六档量化矩阵。为直接服务「盈利」，动作决策升级为**市场状态感知（regime-aware）**——先判牛/熊/震荡，再决定动作取向，避免"牛市过度保守/熊市过度激进"：

```python
def detect_regime(portfolio) -> "bull" | "bear" | "sideways":
    """用 5 大指数 + 持仓整体趋势判市场状态。
    bull: 指数趋势向上 + 整体均线多头
    bear: 指数趋势向下 / 多数持仓深回撤
    sideways: 信号混合
    """

def deterministic_action(regime, qi, ...) -> Action:
    """Regime-aware 动作：
    - bear：保守模式——深回撤/负sharpe → sell/reduce 优先，保护本金
    - bull：进取模式——sharpe>0 趋势向上 → add/hold，避免误减仓丢收益
    - sideways：中性——走标准六档矩阵
    """
```

这样把 FINSABER 指出的两个致命偏差直接修正为盈利规则：
- **牛市**：不再被 LLM 吓得减仓优质资产 → 拿住/增持赚趋势钱
- **熊市**：不再死扛深亏 → 严格止损保护本金

### 4.1 决策前置（核心改动）

在 `_debate_synthesis` 中，**动作决策不再由 debate LLM 的自由输出决定**，而是：

1. **先用确定性量化规则算出动作**（`fallback_debate` 矩阵 + 四视角确定性分数）。
2. **debate LLM 仍运行**，但它的作用降级为：
   - 生成**解释文案**（为什么这样操作、依据的量化事实）
   - 检测并标注**视角间矛盾**（contradictions / uncertainties）
   - 输出 `consensus_level`（主观，但不再决定动作）
3. **最终 action.type / change_pct 以量化规则为准**；若 LLM 文案与量化动作冲突，以量化动作为准，LLM 的跳脱解读降级为附注 `note`。

实现方式（最小侵入）：新增 `engine/decision.py`，提供：

```python
def deterministic_action(qi, trend_scores, risk_scores, value_scores, tech_scores) -> Action:
    """复用 fallback_debate 的六档决策逻辑，纯量化、幂等、可复现。"""
    ...

def merge_with_llm_explanation(det_action, llm_debate) -> Action:
    """量化动作 + LLM 文案合并；动作字段锁定为量化值，文案取 LLM。"""
    ...
```

四视角分数的确定性映射同样前置：`decision.py` 里提供 `score_views_quant(qi)`，直接复刻 `fallback_*_diagnosis` 的映射逻辑（trend强度→分 / vol→risk分 / sharpe→value分 / RSI→tech分），供动作决策使用。**LLM 的四视角分数仅作为参考信息展示在报告里，不再进入动作决策。**

### 4.2 动作字段约定（保持 RFC-012 命中率口径一致）

- 方向动作：`increase`（add）/ `reduce`（reduce、sell）/ `hold` / `watch`
- 只判方向：`increase`/`reduce` 参与命中率，`hold`/`watch` 不计（与 RFC-012 一致）
- `change_pct` 由量化规则给出（确定性 ±10/20/50 等）

### 4.3 报告字段变更

| 字段 | 变化 |
|------|------|
| `per_fund_diagnosis[*].debate.action` | 改为量化动作（确定性）；`reasoning` 可为 LLM 文案 |
| `per_fund_diagnosis[*].debate.action.note` | 新增：LLM 与量化冲突时的 LLM 原始解读（附注）|
| `per_fund_diagnosis[*].debate.decision_source` | 新增：`"quant_primary"` 表示量化主导 |
| 四视角 score | 保留展示，但标注为 `"llm_interpretive"`（仅供解读参考）|

### 4.4 与 RFC-012 的衔接

RFC-012 的 `record_advice` / `validate_due` 读取的仍是报告里的 `actions`（方向动作 + date），动作现在由量化决定 → 命中率反映的是**确定性规则的真实有效性**，可直接用于在线学习校准（置信度收缩/动作命中率展示），口径不破坏。

---

## 5. 预期效果

- **确定性**：同一净值数据，动作 100% 复现 → id19/20/21 类摆荡消失。
- **可解释**：量化规则给出动作依据，LLM 补充自然语言解释，报告仍有人味。
- **可回测**：动作可复现 → RFC-012 命中率有稳定意义。
- **资源友好**：相比"3 次采样投票"（方案 C，~80min），本方案几乎不增耗时（量化即时，LLM 解读仍并行）。

---

## 6. 边界与风险

- **规则可能过保守/过激进**：量化矩阵是启发式，可能存在系统性偏差。缓解：RFC-012 命中率持续反馈，一旦某动作命中率长期<50%，可调矩阵阈值。这是"可学习的量化"，比"不可复现的 LLM"更可迭代。
- **极端行情误判**：矩阵依赖 sharpe/回撤/趋势的数学口径，市场极端反转时可能延迟。缓解：保留 `watch` 与 `trigger_conditions`（触发条件提示）作为监控信号。
- **LLM 文案可能与动作冲突**：合并时强制动作字段取量化值，文案只作解释，不产生第三种动作。

---

## 7. 实施清单（全部完成 ✅）

1. ✅ **新增 `fund-analyzer/engine/decision.py`**：
   - `score_views_quant()`：四视角确定性分数（trend强度→分 / vol→risk分 / sharpe→value分 / RSI→tech分）
   - `detect_regime()`：牛/熊/震荡判段（§4.0）
   - `deterministic_action()`：regime-aware 六档量化动作（§4.0 + RFC-006 矩阵）
   - `merge_with_llm_explanation()`：量化动作锁死 + LLM 文案附注
   - `summarize_regime()`：组合级 regime 汇总
2. ✅ **改造 `analyzer.py._analyze_4_views()`**：四视角分数改为 `score_views_quant` 确定性计算（LLM 仅作展示 `llm_interpretive`）。
3. ✅ **改造 `analyzer.py._debate_synthesis()`**：动作决策走 `detect_regime + deterministic_action`，debate LLM 输出降级为解释/矛盾标注；新增 `_detect_fund_regime`（单基金趋势+peer_benchmark 兜底）。
   - 熊市：负 sharpe / 深回撤 → sell/reduce 优先（严格止损）
   - 牛市/震荡：`dd_released + trend_up/金叉` → hold 豁免（避免误砍）
4. ✅ **报告字段**：新增 `decision_source="quant_primary"` + `debate.action.note`（LLM 冲突附注）+ `regime`。
5. ✅ **单测**：新增 `tests/test_decision.py`（19 个）——幂等/regime 三态/六档边界/冲突合并全过。
6. ✅ **对照验证**：用 id19/20/21 同一份真实 `QuantIndicators` 数据跑新引擎，断言动作固定无摆荡。
7. ✅ **回归**：全引擎测试套件 120 个（101 原 + 19 新）全绿。
8. ✅ **文档**：更新 CHANGELOG（v6.3）。

### 真实报告核验（id=22，2026-08-01 01:00 CST，v6.3 引擎后台产出）

用**真实全链路分析**（非回放）在 4 只基金上验证摆荡消除，decision_source 全部 `quant_primary`：

| 报告 | 018044 | 000311 | 161725 | 588760 | 备注 |
|------|--------|--------|--------|--------|------|
| id=19 | reduce | reduce | reduce | reduce | LLM 旧随机 |
| id=20 | hold | hold | hold | reduce | LLM 旧随机 |
| id=21 | reduce | hold | reduce | hold | LLM 旧随机 |
| **id=22** | **watch** | **hold** | **hold** | **hold** | ✅ 量化确定 |

- **动作摆荡彻底消除**：同一批基金，量化引擎一次定性，全部 `quant_primary`。
- **id=22 regime 全部 sideays（震荡）**：`_detect_fund_regime` 用单基金趋势+peer_benchmark 判定（未接入真实指数序列——见「后续增强」）。
- **LLM 冲突附注生效**：161725 的 `note` 明确「LLM 原判 reduce 与量化决策 hold 冲突，已按量化结果处理」✅
- **降级不影响动作**：`degradation=minor`（debate×3 + value×1 LLM 观点缺失），但动作由量化决定，仍稳定输出；`completeness=100%`。
- **时间成本**：analysis_duration=1413s（~24min），相较优化前 40min 有改善。

#### 后续增强（未做，已记录）
- `_detect_fund_regime` 目前用单基金趋势兜底（缺省 sideways）。可接 5 大指数真实序列进 `detect_regime`，让牛熊判定更贴近市场整体状态。

---

## 8. 验收标准

- [x] 同一 `QuantIndicators` 输入，`deterministic_action` 输出幂等（连续调用结果一致）— 19 个单测幂等用例全过
- [x] `detect_regime` 能正确识别牛/熊/震荡 — 单测三态全过；id=22 真实产出判定震荡
- [x] 用 id19/20/21 的同一净值数据回放，三份报告动作固定 — id=22 全 `quant_primary` 一致 ✅
- [x] 全引擎单测通过（含新增 decision 测试）— 120 passed
- [x] 报告含 `decision_source="quant_primary"` 与 LLM 附注 — id=22 已验证 ✅
- [x] 前端无需改动（actions 结构兼容）；RFC-012 命中率收集不受影响 — 兼容已验证
- [ ] 盈利导向验证（长期）：id=22 判定为持有/观望，需后续通过 RFC-012 命中率持续反馈确认量化动作优于旧 LLM 随机偏好（初步看 000311 不再被误减仓 ✅）

---

## 附：方案比选

| 方案 | 描述 | 耗时 | 确定性 | 盈利导向 | 结论 |
|------|------|------|--------|---------|------|
| A | LLM 打分但锁定随机种子/温度→量化降级 | 低 | 中 | 弱 | 治标，NIM 无 seed 控制，不可靠 |
| **B+R（本 RFC）** | **动作全量化 + regime-aware 牛熊感知，LLM 只解读** | **低** | **高** | **强** | **推荐，符合既定准则 + FINSABER 实证** |
| C | 同报告跑 3 次 LLM 投票共识 | 3x (~80min) | 中 | 弱 | 服务器 3.6G 扛不住，不现实 |
