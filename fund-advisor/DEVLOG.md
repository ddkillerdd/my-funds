
## RFC-021 增量资金分配修复 (2026-08-06)

### 问题(用户反馈"报告错漏百出")
- 用户设 `total_capital_rmb=10`(本意=本次可用增量资金/子弹)
- 旧逻辑把 total_capital 误当「组合总市值」作金额基数 → `current_amount=10×权重`错、`target_amount=10×47.7%=4.77`谬误
- 单只持仓(纳斯达克1.49)但权重100% → 旧逻辑误判「减仓」, 输出 action_amount=-5.26 荒谬
- 根因: 「现有持仓市值」与「可用增量资金」被糊成一个 total_capital 字段

### 修复(底层从引擎改)
- 新增 `../fund-analyzer/engine/allocation.py` 组合级增量分配器
  - 目标盘子 T = Σcurrent_mv + available_capital
  - 每基金 ideal_i = T × target_weight(方向+波动率目标已含风险调整, 稳健不依赖收益预测)
  - action_amount = ideal - current_mv (>0加/<0减); 增量不足按 ideal 比例压缩
  - 分配方法: 采用风险平价思想+引擎既有 target_weight(调研结论: 比纯MVO/收益排名稳健)
- `engine/decision.py build_position_action`: 新增 current_mv 参数, current_amount=真实现值
- `engine/analyzer.py`: 金额基准改为 Σcurrent_mv+可用资金; 新增 `_apply_incremental_allocation` 在 Step2后统一精修 target/action 金额; 正action_amount时把hold/reduce改判increase, 负时改判reduce
- `backend/models.py PortfolioInput`: 拆 total_capital(兼容) + available_capital(新)
- `backend/services/config_service.py`: 新增 get/set_available_capital, key=available_capital_rmb, 旧key回退
- `backend/api/config.py`: 新增 GET/PUT /api/config/available-capital
- 前端 AdvisorView: 标签改「可用增量资金」, 新增「增量资金分配」展示卡(目标盘子/可用/已分配/说明)
- 报告输出新增 incremental_allocation 摘要 + holdings_health.current_amount/current_mv/total_scale/allocated_capital

### 已验证(端到端 report id=45)
- 018044 纳斯达克: 现持1.49 → 目标5.48 → 建议加仓3.99 (之前是错的 减仓-5.26/目标4.77)
- incremental_allocation: 目标盘子11.49 = 现有1.49 + 可用10, 分配3.99, 足额
- 前端 build OK, 后端 systemd 重启生效, 语法全通过



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

### v6.0 — RFC-010 荐基 + 择时 部署上线 ✅ 完成 (2026-07-31)

#### 代码改动 (后端 + 前端)

| 文件 | 改动 |
|------|------|
| `backend/schemas/advisor_recommend.py` | 新增：TimingRequest/Response、ScreenRequest/Response、CandidateIn、RecommendationOut/FactorScoreOut |
| `backend/services/recommend_service.py` | 新增桥接：get_timing()（调 engine/timing）、run_screen()（调 engine/screen_runner）；复用 NavService 取持仓 NAV 作分散化参照 |
| `backend/api/recommend.py` | 新增 2 端点：POST /api/advisor/recommend/timing、POST /api/advisor/recommend/screen |
| `backend/api/router.py` | 注册 recommend router（prefix=/api/advisor/recommend） |
| `frontend/src/views/RecommendView.vue` | 新增「荐基 & 择时」双 Tab 视图（择时因子进度条 + 荐基排序表） |
| `frontend/src/router/index.js` / `App.vue` | 注册 /recommend 路由 + 侧边栏菜单项 |
| `frontend/src/api/index.js` | 新增 getFundTiming / screenFunds |

#### 能力
- **择时**（纯量化，无 LLM）：技术/趋势/回撤/估值 4 因子 + 硬风险门 + 定投建议
- **荐基**（六因子）：动量/质量/回撤/分散/规模/估值 → 排序 + 风格归因 + 建议配比；可选 LLM 后置一句解读（只解读不评分）

#### 验收（真实线上 HTTP 验证）
- timing 161725 → **avoid**（RSI=73 超买 + 偏离MA20 9.4% + 回撤64.5%，风险门拦截）✅
- screen [161725/110022/005827] → 消费35.4 / 蓝筹31.0 / 白酒23.8，风格归因创业板指/上证50 ✅
- 无效代码 999999 → 优雅降级 nav_data_insufficient ✅
- 空候选 → no_candidates ✅
- 前端 vite dev 热更已生效；后端 systemd 已重启（fund-advisor-backend.service active）

#### 遗留
- 荐基 with_ai_explanation 默认关（避免 ds-flash 高峰 529 拖慢）；前端已提供开关
- 内存约束：荐基候选 ≤10 只，逐个处理，峰值 <200MB

### v6.0.1 — 修复：每日重复邮件 (2026-07-31)

#### 问题
今早(07-31)收到 3~4 封一模一样的分析邮件。根因：
- 主因：OpenClaw cron「FundAdvisor daily analysis push」`timeoutSeconds=180`，但 AdvisorJob 分析要 ~30min（27+次LLM调用+fallback）。curl在180s被judge超时 → cron重试 → curl重复执行 → 累计起 4 个并发 AdvisorJob → 4 封同样邮件（同一份净值和持仓，内容雷同）。
- 无幂等保护：`run-advisor` 端点对每个请求都无条件「分析+发邮件」。

#### 修复（A+B）
- **A 每日幂等锁**：新增 `backend/models/email_send_record.py`（表 `email_send_record`，`report_date` 唯一约束）。`AdvisorJob.run()` 发邮件成功后 `_mark_sent()` 落库；下次同一天再跑会 `skipped=True` 直接跳过，不重复分析不发邮件。并发竞争由 DB 唯一约束兜底。新增 `force` 查询参数可绕锁强制重发。
- **B 调 cron 超时**：`timeoutSeconds 180 → 2400`（40min 覆盖分析时长），不再误判超时触发重试。cron message 注明幂等锁已生效。

#### 验证
- 单测（mock LLM+Mail）：第1次发(1次) / 第2次 skipped(仍1次) / force=True 再发(2次) ✅
- `email_send_record` 表 create_all 自动建表成功 ✅
- OpenAPI 确认 `/api/scheduler/run-advisor` 参数 `[push_email, model, force]` ✅
- backend systemd 重启生效（中间等分析跑完自然优雅停机，未强杀）

#### 遗留
- AdvisorJob 全量分析 ~30min，cron 40min 超时已覆盖；若未来模型更慢需再调

### v6.0.2 — 优化：分析提速 + 规避不稳定模型 (2026-07-31)

#### 问题背景
监控一次全量分析（17:20-17:59, 40min）发现超时灾难：
- ds-flash 100% 超时 (0成功/16超时) — 完全不可用
- nemotron-30b 52% 超时 (11成功/12超时)
- nano-9b 0% 超时 (7成功/0超时) — 唯一稳定模型
- 4 只基金 debate 全模型失败 → 量化兜底，质量降级

根因: model_assignments 里 value/debate 首选 ds-flash（最强推理本意），
但 ds-flash 每次都先白等 60s×2 重试才 fallback，拖慢整体 + 大部分观点缺失。

#### 修复 (advisor_service.py _analyze_v3 配置)
- 所有视角(趋势/风险/价值/技术/辩论/组合/交叉验证)首选 → nano-9b（0超时主力）
- default_timeout 60→35s / fallback_timeout 90→45s (快速失败, 不白等)
- ds-flash 从首选移除, nemotron-30b + ds-flash 降为 fallback_models 最后兜底
- 备份: /tmp/advisor_service.py.bak

#### 预期效果
- 超时等待从 33次×~60s 降到接近 0 (nano-9b 0超时)
- 全量分析 40min → ~20min 以内
- value/debate/portfolio 不再因 ds-flash 超时缺失, 辩论质量恢复

#### 验证
- 语法/配置断言通过 (所有角色均 nano-9b, ds-flash 无首选)
- backend systemd 重启生效 (PID 3614674)
- 完整全量分析验证待下次触发时观察

## 2026-08-05 AI顾问页面空白修复
- 症状: /advisor 页面空白(全站其他页正常)
- 根因: AdvisorView.vue 用了 computed(reportDate) 但 import { ref, onMounted } from "vue" 漏导 computed → ReferenceError: computed is not defined → setup崩溃 → 白屏
- 修复: import 加 computed
- 验证: chromium headless 确认 JS无报错, 页面渲染出 AI投资顾问/市场环境分析/总资金 等
