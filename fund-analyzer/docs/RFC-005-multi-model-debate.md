# RFC-005: 多模型辩论引擎 — 从单模型自言自语到跨模型对质

> **状态**: Draft  
> **日期**: 2026-07-30  
> **作者**: AAA  
> **前置**: RFC-004 (FundAnalyzer v3 量化引擎)

---

## 1. 问题陈述

### 当前架构的致命缺陷

FundAnalyzer v3 的 4 视角辩论架构是**正确的骨架**——趋势/风险/价值/技术各自独立诊断 → 辩论裁决 → 组合结论。但当前所有视角共用同一个模型 `nemotron-nano-9b-v2`，这等于**一个人从 4 个角度自言自语**。

实证（30 分钟前的测试）：
- 588760 最大回撤 -59.28%，Risk LLM 给 82 分（明显高估）
- 因为同一个模型在所有视角下的"风险直觉"是相同的——它不会自己反对自己

### 为什么多模型辩论有效

TradingAgents 论文的核心发现：多方/空方独立写报告 → 综合裁决的机制，累计收益 26.6% vs 基准 -5.2%。关键不在"多"，而在**认知差异被显式检测**。

arXiv:2507.22936（2025）的 FinBen 大规模 benchmark 证实：
> "using multiple models together or hybrid frameworks can help reduce the biases of individual models"

不同 LLM 在同一金融任务上的表现差异显著——GPT-4 擅长信息抽取，Gemini 擅长预测，Claude 擅长多文档分析。这种**认知多样性**正是辩论质量的前提。

---

## 2. 模型评估（今天实测）

### 2.1 可用模型列表

通过 NewAPI `/v1/models` 确认 11 个模型：

```
nvidia/nvidia-nemotron-nano-9b-v2           ✅ 1-2s, 当前主力
nvidia/nemotron-3-nano-omni-30b-a3b-reasoning ✅ 1-2s, 30B 参数
deepseek-ai/deepseek-v4-flash               ⚠️ 2-7s, 33% overload
stepfun-ai/step-3.7-flash                   ❌ rate-limited, 12s+
stepfun-ai/step-3.5-flash                   ⚠️ 未测试
minimaxai/minimax-m3                         ❌ rate-limited, 49s+
mistralai/mistral-large-3-675b              ⚠️ 未测试
meta/llama-3.2-11b-vision                   ⚠️ 多模态, 金融推理未知
z-ai/glm-5.2                                 ❌ timeout, 165s
```

### 2.2 Trend 视图对比测试

同一 prompt（018044 纳斯达克、161725 白酒），同温度 0.3：

| 维度 | nano-9b | omni-30b | ds-flash |
|------|---------|----------|----------|
| **分析深度** | 75/67 | **189/161** | 161 |
| **诊断条数** | 4 | **5** | 5 |
| **平均每条字数** | 19 | **38** | 32 |
| **短期视角** | ✅ | ✅ | ✅ |
| **长期视角** | ❌ | ✅ | ❌ |
| **风险带具体数据** | ❌ | ✅ | ✅ |
| **延迟** | 27-34s | 30-55s | ~30s |
| **稳定性** | ✅ 0/2 失败 | ✅ 0/2 失败 | ❌ 1/6 overload |

### 2.3 认知多样性验证

**018044（纳斯达克）趋势分析**：

- **nano-9b**: 关注均线空头排列、MACD死叉、RSI超卖 → 给出**纯短期技术面**判断
- **omni-30b**: 关注均线偏离 MA20 的百分比、最大回撤 -21.5%、布林下轨反弹 → 给出**技术面+风险面**综合判断
- **ds-flash**: 关注 MACD+RSI 共振、布林下轨、当前回撤 -11.12% → 给出**成交量预期+反转信号**判断

**3 个模型对同一只基金的关注点显著不同。这不是错误，这是辩论价值的基础。**

---

## 3. 设计方案

### 3.1 核心原则

> **不同模型 = 不同世界观。同一个模型分 4 个角色 = 同一世界观换 4 套说辞。**

```
旧架构（单模型）:
  nemotron-nano → Trend View
  nemotron-nano → Risk View      ← 全部是同一"大脑"
  nemotron-nano → Value View       没有真正的认知冲突
  nemotron-nano → Tech View

新架构（多模型）:
  omni-30b     → Trend View      ← 30B 参数, 趋势判断全面
  omni-30b     → Risk View       ← 风险量化能力强
  ds-flash     → Value View      ← GPT-4 级推理, 价值分析准
  nano-9b      → Tech View       ← MACD/RSI 形态识别, 9B 够用

  ds-flash     → Debate           ← 最强推理做裁判
  omni-30b     → Portfolio        ← 组合诊断需全面视角
  nano-9b      → CrossValid       ← 审计需要细节检查
```

### 3.2 模型分派策略

| 步骤 | 分配模型 | 理由 | 备选模型 |
|------|---------|------|---------|
| **Trend View** | omni-30b | 趋势分析需要全面视角（短+长期），测试中 omni 的 depth 是 nano 的 2.5x | nano-9b |
| **Risk View** | omni-30b | 风险量化需具体数据支撑，omni 测试中 key_risk 都带了数值 | nano-9b |
| **Value View** | ds-flash | 价值分析需要最强推理——判断 Sharpe/Sortino/Calmar 综合性价比 | omni-30b |
| **Tech View** | nano-9b | MACD/RSI/布林带形态识别不需要大模型，9B 足够 | omni-30b |
| **Debate** | ds-flash | 辩论是裁判位，需要检测 4 个观点间的细微矛盾 | omni-30b |
| **Portfolio** | omni-30b | 组合层面需同时看收益/风险/相关性/集中度，全面视角 | ds-flash |
| **CrossValid** | nano-9b | 交叉验证是清单式检查，不需要深度推理 | ds-flash |

**总计**: omni-30b 调用 ~8 次, nano-9b ~8 次, ds-flash ~6 次

### 3.3 Fallback 链

每个角色有独立的 fallback 策略：

```
Trend/Risk View:
  omni-30b → (失败) → nano-9b → (失败) → 纯计算降级

Value View:
  ds-flash → (失败/overload) → omni-30b → (失败) → 纯计算降级

Tech View:
  nano-9b → (失败) → omni-30b → (失败) → 纯计算降级

Debate (裁判位, 最关键):
  ds-flash → (overload) → 等 5s 重试 1 次 → (仍失败) → omni-30b → (失败) → 无辩论降级

Portfolio:
  omni-30b → (失败) → ds-flash → (失败) → 纯计算降级
```

### 3.4 Debate Agent 的两层裁决

多模型引入后，辩论需要比单模型更精细：

**第一层：信号级对齐检查**
```
输入: 4 个视图的诊断列表（各自带 model 标签）

检查:
1. Trend 说"下跌"但 Value 说"低估" → 这不是矛盾（趋势是短期，价值是长期）
2. Trend 说"RSI 超卖=反弹"但 Tech 说"RSI 超卖=继续跌" → 这是真正矛盾
3. Risk 说"波动率 15%=中等"但另一模型在同一只基金上说"波动率 15%=高风险" → 阈值分歧

输出:
- consensus_level: strong/broad/moderate/sharp_disagreement
- contradictions: [每条矛盾的详细信息, 含相关模型标签]
```

**第二层：模型级可靠性检查**
```
输入: debate 结果 + 各模型的输出元数据

检查:
- ds-flash 是否频繁 fail？→ 如果是，降低其权重
- omni-30b 和 nano-9b 在"方向判断"上不一致？→ 查看哪个更符合量化真值
- 某个模型的输出质量是否显著低于其他？→ 标记为异常

输出:
- model_reliability: {omni-30b: 0.85, nano-9b: 0.72, ds-flash: 0.80}
- conflict_models: [涉及矛盾最多的模型]
```

### 3.5 最终 Confidence 公式

```
overall_confidence =
  base_quality（数据完整性得分）
  × model_reliability（各模型可用性加权平均）
  × consensus_factor（4 视图一致性, 1.0=完全一致, 0.3=严重分歧）
  × data_quality（历史长度/指标完整度）
```

当 `consensus_factor < 0.5` 时（4 个模型产生了严重分歧），强制降级置信度到 `low`，并警告："本次分析存在显著模型间分歧，建议参考量化真值自行判断。"

---

## 4. 实现变更

### 4.1 需要修改的文件

| 文件 | 改动 |
|------|------|
| `engine/analyzer.py` | 重写 `_analyze_4_views()` — 按视角分派模型；`_run_debate()` — 两层裁决 |
| `engine/llm_client.py` | 新增 `model_assignment` 载入可用模型列表；强化 `reasoning` 字段处理 |
| `engine/prompts.py` | Debate prompt 增加 model 标签和 reliability 检查 |
| `engine/models.py` | `DebateSummary` 增加 `model_reliability`/`conflict_models` 字段 |
| `advisor_service.py` | `LLMConfig` 改为多模型配置 |

### 4.2 不破坏

- 量化层 (quant.py) 不变
- 输入/输出 schema 仅扩展字段，不删除
- API 向后兼容
- 4 基金完整分析预计耗时 ~650s（omni-30b 比 nano 略慢，ds-flash 有重试）

---

## 5. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| ds-flash 频繁 overload | 中（33%） | 中等 | debate/portfolio 有 omni 降级 |
| omni-30b origin 限制 | 低 | 严重 | 保留 nano 降级 |
| 多模型总延迟超预期 | 中 | 小 | 降级后 nano 单模型更快 |
| 模型间结论差异过大 | 高 | **这是好事** | 通过 debate 显式标注、降低置信度 |

---

## 6. 参考

- TradingAgents (Xiao et al., 2024) — arXiv:2412.20138
- FinBen Benchmark (NeurIPS 2024) — 42 datasets, 24 tasks
- arXiv:2507.22936 — Multi-model evaluation bias reduction hypothesis
- DX Research Group — Prompt position experiment (3% vs 74% citation rate)
- ai-hedge-fund (virattt, 50K⭐) — 18-agent style diversity architecture
