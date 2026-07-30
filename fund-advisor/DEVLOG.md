

### v5.0 — RFC-005 多模型辩论 ✅ 完成 (2026-07-30 22:10-22:50)

#### 代码改动 (5 文件)

| 文件 | 改动 |
|------|------|
| `engine/models.py` | DebateSummary 加 `model_sources`/`model_reliability`/`conflict_models` 3 字段；AnalysisReport 加 `model_roles` |
| `engine/llm_client.py` | LLMConfig 支持 `model_assignments` dict；call() 支持 `model=` 覆盖 |
| `engine/analyzer.py` | _analyze_4_views 按视角分派+独立fallback；_debate_synthesis 注入模型来源；_portfolio_synthesis/_cross_validate 使用指定模型；analyze() 填 model_roles |
| `advisor_service.py` | LLMConfig 传入 model_assignments；_report_to_api_json 导出 model_sources/reliability/conflict_models |

#### 模型分派策略
- **trend/risk** → omni-30b → nano-9b
- **value/debate** → ds-flash → omni-30b
- **tech/cross_val** → nano-9b → omni-30b
- **portfolio** → omni-30b → nano-9b

#### 验收结果 (报告 #18)
- 耗时 830s / LLM 27次 / 失败 5次（全自动降级，无人工干预）
- **model_sources 正确输出**：0…4/omni-30b, risk→omni-30b, value→ds-flash/omni, tech→nano-9b
- **model_reliability 正确输出**：各模型 0.7 基础分
- **conflict_models 正确为空**（全部 fallback 后一致性强）
- 161725 (白酒) health=45 最低 — consensus 0.55 (partial_disagreement)
- 588760 (科创) 年化波动 78%、最大回撤 -59% — 极端风险
- 161725 value→ds-flash 被 529 overload → 降级 omni-30b — fallback链生效 ✅

#### 遗留问题
- ds-flash 晚上 529 overload 严重（高峰期），大量降级到 omni-30b
- portfolio_diagnosis.health_label/score 在 JSON 中为 None — `_report_to_api_json` 里的字段取值问题（不影响前端，前端用的是 per_fund）

### v5.1 — Bugfix 代码审查 (2026-07-30 23:21)

#### 文档
- `docs/bugfix-v5.md` — 10 个 bug 详细记录

#### 修复 (6 个)
| Bug | 修复 |
|-----|------|
| actions 前两条无 fund_name | `_report_to_api_json` 从 per_fund_diagnosis 查名填入；`GET /report` 和 `GET /report/{id}` 都做后处理补全 |
| concerns/risks 带证据括号 | 后端正则改宽+前端 cleanEvidence 双重清洗 |
| portfolio_diagnosis 字段缺失 | 加 overall_health_score/overall_health_label 字段 |
| 日志含省略号 U+2026 | 改 ASCII |
| import re 在循环内 | 移到文件顶部 |
| GET /report (latest) 没补全 fund_name | 提取 _patch_report_actions 公共函数 |
