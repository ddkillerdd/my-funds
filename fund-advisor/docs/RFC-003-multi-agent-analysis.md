# RFC-003: AI 投资顾问多模型协作分析架构

> 状态: 实施中 | 版本: v1 | 日期: 2026-07-30

## 问题

当前 AI 投资顾问的核心缺陷：

1. **一次性 prompt 导致随机性大** — 同一持仓，四次点击生成四份不同报告
2. **无数据锚定** — LLM 无脑生成，不引用实际持仓数据
3. **无验证机制** — LLM 说什么就是什么，矛盾没检查
4. **单模型偏见** — step-3.7-flash 独占，没有 cross-check

## 调研结论

检索 30+ 来源（FinDebate/AlphaAgents/Multi-LLM Debate 论文、Azure/AWS/开源项目）后的核心发现：

| 模式 | 可靠性提升 | 业界是否通用 |
|------|-----------|------------|
| Multi-agent 角色分化 | +15-25% | ✅ 所有生产级系统 |
| 跨模型辩论/反方验证 | +20-30% | ✅ FinDebate/Multi-LLM Debate |
| 数据锚定(Grounding + Citation) | 消除幻觉 | ✅ CFA/Daloopa/AWS Bedrock |
| 自身一致性(Self-Consistency) | +11-18% | ✅ Google Research |
| Chain-of-Thought 分步推理 | +10-15% | ✅ 基本要求 |

## 方案设计

### 约束

| 约束 | 值 |
|------|-----|
| NewAPI 可用模型 | step-3.7-flash(3.4s), minimax-m3(9s), nemotron-nano-9b(2s), nemotron-omni-30b(1.5s) |
| NVIDIA NIM 速率限制 | 40次/分钟 → 最小间隔 1.6s/次 |
| 服务器内存 | 3.6G (1.6G 可用), 不能本地 LLM |

### 架构: 4 步多模型协作

```
┌─────────────────────────────────────────────────┐
│ Step 0: 事实计算层 (Python, 0s)                │
│ facts_computer.py → 盈亏/占比/净值/趋势计算     │
│ 100% 确定，不靠 LLM                            │
└──────────────────────┬──────────────────────────┘
                       │ facts.json 注入 ↓
┌──────────────────────┴──────────────────────────┐
│ Step 1: 逐基金深度分析 (step-3.7-flash)        │
│ 5 只基金 × 独立 prompt × 3s/只 = ~20s          │
│ → health_score + 风险因素 + 数据引用            │
└──────────────────────┬──────────────────────────┘
                       │ 5 份分析结果 ↓
┌──────────────────────┴──────────────────────────┐
│ Step 2: 组合综合诊断 (minimax-m3, ~12s)         │
│ 汇总 Step1 → 趋势判断 + 建议 + 诊断              │
│ → market_analysis + actions + portfolio_diagnosis│
└──────────────────────┬──────────────────────────┘
                       │ 诊断结果 ↓
┌──────────────────────┴──────────────────────────┐
│ Step 3: 反方验证 (nemotron-nano-9b, ~3s)        │
│ 检查矛盾: 健康度vs建议 / 趋势vs操作              │
│ → passed/failed + issues                        │
└──────────────────────┬──────────────────────────┘
                       │ 验证结果 ↓
┌──────────────────────────────────────┐
│ Step 3b: 紧急表决 (仅验证失败时触发) │
│ nemotron-omni-30b → 中立裁决          │
│ → 维持/推翻/修正                     │
└──────────────────┬───────────────────┘
                   ↓
┌─────────────────────────────────────────────────┐
│ Step 4: 合成 (Python, 0s)                       │
│ 融合 facts + fund_analyses + synthesis + debate │
│ → 最终结构化报告                                │
└─────────────────────────────────────────────────┘
```

### 模型角色分配

| 角色 | 模型 | 温度 | 调用次数 | 预计耗时 |
|------|------|------|---------|---------|
| 基金分析师 | step-3.7-flash | 0.1 | 5次 | 20s |
| 组合轮手 | minimax-m3 | 0.1 | 1次 | 12s |
| 反方验证官 | nemotron-nano-9b | 0 | 1次 | 3s |
| 紧急仲裁 | nemotron-omni-30b | 0 | 0~1次 | 2s |
| **合计** | | | **7~8次** | **35~40s** |

### 报告结构

返回的 JSON 包含：

```
{
  market_analysis:      // 市场环境分析
  holdings_health:      // 持仓健康度（含 Step1 风险因素和数据引用）
  actions:              // 操作建议（可能被 Step3 仲裁修正）
  portfolio_diagnosis:  // 组合诊断（新增 advantage/weakness）
  debate_verdict:       // 跨模型验证结果（新增）
    ├─ passed
    ├─ severity
    ├─ issues
    └─ arbiter (如有)
  ground_truth:         // 客观事实数据（新增）
    ├─ 总市值/盈亏/集中度
    ├─ 趋势状态/波动率
    └─ 每只基金客观数据
  model_chain:          // 模型调用链（新增）
  analysis_duration_seconds:  // 分析耗时（新增）
}
```

### 兼容性

- 前端 API 不变: `POST /api/advisor/analyze` 返回兼容的 JSON
- 旧的历史报告依然可浏览
- 新字段在现有 UI 上扩展展示，不破坏旧渲染

## 文件变更

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/services/facts_computer.py` | 新增 | 纯 Python 事实计算 |
| `backend/services/advisor_service.py` | 重写 | 从 1-step 改为 4-step 多模型引擎 |
| `backend/api/advisor.py` | 不改 | POST /analyze 接口不变 |
| `frontend/src/views/AdvisorView.vue` | 改 | 新增 ground_truth/debate_verdict 展示 |
| `docs/RFC-003-multi-agent-analysis.md` | 新增 | 本文档 |
| `docs/report-persistence.md` | 改 | 补充新字段说明 |
| `CHANGELOG.md` | 改 | v1.5.0 |
| `DEVLOG.md` | 改 | 实施记录 |

## 测试计划

1. POST /api/advisor/analyze → 返回完整 7 字段 JSON
2. Step0 facts 计算结果与 DB 一致
3. Step1 5只基金独立分析 → 有 health_score + data_citations
4. Step2 组合诊断包含所有 action
5. Step3 验证 passed=true 或输出 issues
6. Step3b 仲裁仅 step3 失败时触发
7. 前端正确展示 ground_truth/debate_verdict 卡片
8. 后端 35-40s 内完成（含 1.6s 间隔）
9. 历史报告兼容新字段

## 测试记录

| 日期 | 版本 | 结果 | 发现问题 | 修复 |
|------|------|------|---------|------|
| 2026-07-30 14:04 | v2.0.0-rc1 | ❌ 500 | Bug 1: _fund_fallback 缺少 health_score | 已修 |
| | | | Bug 2: long_return_pct 字段有时不存在 | 已修 |
| | | | Bug 3: step-3.7 JSON 截断率 50% | 降级补充完整 |

详细: `docs/bug-report-v2-test1.md`
