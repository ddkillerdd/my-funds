# RFC-018 · AI投顾"长期投资方案中心" — 详细设计

> 版本: v0.1 (2026-08-03) | 依赖: 调研 + 架构
> 定位: 开发准备, 可照此直接写代码。复用现有引擎(不重造)。

---

## 1. 数据表设计 (SQLAlchemy, 新增 4 表)

### 1.1 `fund_candidate` — 全市场基金候选池
```python
class FundCandidate(Base):
    __tablename__ = "fund_candidate"
    id = Column(BigInteger, primary_key=True)
    fund_code = Column(String(10), unique=True, index=True)   # 基金代码
    fund_name = Column(String(200))
    fund_type = Column(String(50))        # 股票/混合/债券/指数/QDII/商品
    style = Column(String(50), default=None)   # 风格标签: 大盘/小盘/成长/价值
    scale = Column(Numeric(16,2), default=None)  # 规模(亿)
    inception_date = Column(Date, default=None)  # 成立日
    latest_nav = Column(Numeric(10,4), default=None)
    nav_change_pct = Column(Numeric(8,4), default=None)
    label = Column(String(200), default=None)     # 行业/主题标签(逗号分隔)
    open_apply = Column(SmallInteger, default=1)  # 是否开放申购
    status = Column(SmallInteger, default=1)
    created_at / updated_at
```
**关键**: 只存候选元信息; 净值按需拉取缓存(sim_tmp 思路), 不无限占库。

### 1.2 `portfolio_plan` — 投资计划(固定预算)
```python
class PortfolioPlan(Base):
    __tablename__ = "portfolio_plan"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(100), default="我的入场计划")
    total_budget = Column(Numeric(14,2))        # 固定预算(如 100)
    used_amount = Column(Numeric(14,2), default=0)   # 已投入
    remaining = Column(Numeric(14,2))           # 剩余 = total - used
    risk_profile = Column(String(20), default="balanced")  # 用户风险偏好: conservative/balanced/aggressive (UI层; 内部映射到现有 playbook+权重缩放, 见§2.3)
    status = Column(String(20), default="draft")  # draft/active/completed
    target_allocation = Column(JSON)             # {fund_code: weight_pct}
    ai_summary = Column(Text, default=None)      # AI 生成的方案解读/理由
    approved_at = Column(DateTime, default=None)
    created_at / updated_at
```

### 1.3 `plan_tranche` — 分批批次(且慢"100份")
```python
class PlanTranche(Base):
    __tablename__ = "plan_tranche"
    id = Column(BigInteger, primary_key=True)
    plan_id = Column(BigInteger, ForeignKey("portfolio_plan.id"), index=True)
    tranche_no = Column(Integer)          # 批次序号 1..N
    units = Column(Numeric(10,2))         # 应投份数(展示: 本批金额/unit)
    window = Column(String(30))           # 择时: now_entry/staged_entry/wait/avoid
    dca_multiplier = Column(Numeric(4,2)) # 倍率: 0.6/1.0/1.3 (来自 dca_planner)
    plan_date = Column(Date)              # 建议执行日
    status = Column(String(20), default="pending")  # pending/executed
    executed_at = Column(DateTime, default=None)
    amount = Column(Numeric(14,2), default=None)    # 实际投入金额
```

### 1.4 `plan_holding` — 计划持仓明细(每个基金盈亏分开记录)
> 用户决定: 每个计划的每只基金**成本/份额/浮盈分开记录**, 独立核算, 不与全局 holdings 混账。
```python
class PlanHolding(Base):
    __tablename__ = "plan_holding"
    id = Column(BigInteger, primary_key=True)
    plan_id = Column(BigInteger, ForeignKey("portfolio_plan.id"), index=True)
    fund_code = Column(String(10), index=True)
    fund_name = Column(String(200))
    # 本次计划累计投入该基金
    total_cost = Column(Numeric(14,2), default=0)   # 已投入成本
    total_units = Column(Numeric(16,4), default=0)  # 累计份额(按各批成交净值折算)
    avg_cost = Column(Numeric(10,4), default=0)     # 平均成本 = total_cost/total_units
    last_nav = Column(Numeric(10,4), default=None)  # 最近净值(每日顾问更新)
    last_update = Column(DateTime, default=None)
    created_at / updated_at
```
- **作用**: 每日顾问跟踪 plan 时, 直接读 plan_holding 算**该计划的浮盈**(`(last_nav-avg_cost)×total_units`), 独立于全局 holdings。
- 明细流水(每批买入)可再按需落 `plan_holding_txn` 表(先不建, 需要时再拆)。

---

## 2. 算法设计

### 2.1 每份金额 & 分批(核心公式)
```
unit = total_budget / 100            # 每份金额(概念分母, 非硬条件)
# 每批投入金额 = 本批预算 × dca.base_amount_pct(倍率)
#   倍率来自现有 dca_planner(估值/趋势/回撤):
#     - 低位/深坑 → x1.3 (多投)     中性 → x1.0 (标准)
#     - 高位/弱趋势 → x0.6 (少投)   dca.enabled=false → 0 (停投) 或 window=avoid
# 计划总时长: 建议 3-6 个月建完(行业惯例), 可配; 批次日期按周/双周生成, 遇节假日顺延。
```
> 口径对齐: 不另造"份数档位", 直接复用现有 `dca_planner.base_amount_pct` 倍率机制,
> 避免两套择时口径打架。每批份数由 `本批金额 / unit` 反推(仅展示用)。

**分批金额分配到单只基金(问题2明确)**
- 每批总金额 = 本批预算 × 组合级倍率(见 2.2);
- 默认按配比权重等比分配: `fund_i 本批金额 = 本批总金额 × weight_pct_i`;
- 叠加**单只择时门控**: 某只基金 `dca.enabled=false` 或 `window=avoid` → 当批**跳过该只**, 份额按加权比例分给其余仍可投基金(确保本批总额投满);
- 本轮未投基金当其信号转好时后续批次补投。

### 2.2 组合级择时(复用 `EntryRecommendation.window` + `dca.base_amount_pct`)
- 现有 `compute_entry_recommendation()` 返回 `EntryRecommendation`:`window`(now_entry/staged_entry/wait/avoid 4档) + `dca.base_amount_pct` + `risk_gate`。
- 组合级倍率 = 各基金 `dca.base_amount_pct` 按配比加权, 再乘预算;
- 判定: 存在 `window=avoid` 且权重≥60% → 本批停投(`enabled=false`); 否则按加权倍率投;
- 单只 `risk_gate.blocked` 会额外压低该只权重或剔除;
- 供 AI 解读层补充"当前市场环境"措辞。
### 2.3 配比权重(复用 + 风控约束)
- 基线: `suggested_ratio_pct`(screener 现成)。
- 风控约束:
  - 单只上限 25%, 下限 5%; 合计 = 100%。
  - **禁止重复(用户决定)**: 规则预筛阶段直接**剔除用户已重仓持有的基金**(依据全局 holdings 在投的), 不允许计划重复买入同一只 → 避免过度集中;
    - 判定: 不在 holdings 中(尚未持有) → 可入; 已持有 → 硬过滤出候选, AI 荐基也不得选(提示词约束)。
  - 高风险类(商品/行业/高波动)按 risk_profile 归一缩放:
    - conservative: 高风险×0.5, 债券/稳健权重上浮
    - aggressive: 高风险×1.2
  - **risk_profile 与现有 playbook 的映射**(不另造策略概念):
    - 现有 `playbook: value/trend/balanced/auto` 是策略风格; 用户"风险偏好"是 UI 层概念。
    - conservative → playbook=balanced + 高风险×0.5;  balanced → playbook=balanced/auto;
    - aggressive → playbook=trend/value(取决于选基) + 高风险×1.2。
    - 荐基与配比实际调用仍走现有 `playbook`, risk_profile 只做权重缩放调节。
- 归一化: `w_i / Σw_i × 100` 保证总和 100%。

### 2.4 回测验证(复用 simulator)
- 输入: `{funds: [{code, amount = total_budget×weight}], windows, target_vol, friction}`
- 输出直接映射 simulator 现有返回 + 新增指标(基于引擎已产出的 `daily` 序列可算, 无需改引擎内核):
  ```
  max_drawdown_recovery_days   # 最大回撤修复时长(借鉴雪球)
  win_rate                     # 盈利概率
  ```
- **回撤修复时长 `max_drawdown_recovery_days` 算法**:
  - 沿 `daily` 序列遍历总市值, 记录每段"从峰顶回落→重新涨回峰顶"的交易日跨度;
  - 取**最深处那次回撤**(与现有 max_drawdown_pct 对应的那一段), 回吐它到"恢复至原峰顶"所需自然日数(兼容非交易日则按自然日/交易日口径标注);
  - 若回测期结束仍未回到峰顶 → 记为 `null` + 文案"仍处回撤修复中"(诚实披露)。
- **盈利概率 `win_rate` 算法**:
  - 以 `daily` 序列逐日滚动:**按该日累计收益/总盈亏是否 >0**, 正向天数 ÷ 总天数 × 100%;
  - 口径 = "历史任一时点持有该方案为正的概率", 非"胜率"或"未来预测" → 展示时注明口径, 避免误导。
- **双路径对比(借鉴 Wallible)**:
  - 一次性: 全部预算按初始配比在首日买入(现有 simulator 即可);
  - 每月定投: 预算等额分摊到 N 期(如每月一期), 每期按当期配比买入, 逐期累积市值 → 需新增一个轻量定投回测封装(复用现有净值序列, 只改资金投入节奏, 不改决策内核)。

---

## 3. 后端 Service (新增)

| Service | 文件 | 职责 |
|---------|------|------|
| `FundPoolService` | services/fund_pool.py | 池温启动/刷新/查询; 调用 nav_service 拉净值 |
| `PlanRecommenderService` | services/plan_recommender.py | 规则预筛 + AI研判 → Top N |
| `PlanAllocatorService` | services/plan_allocator.py | 配比权重 + 风控约束 |
| `PlanBacktestService` | services/plan_backtest.py | 桥接 simulator + 回撤修复时长(异步) |
| `PlanService` | services/plan.py | 资金簿/分批/确认建仓/长期跟踪编排(核心) |

### 编排核心 `PlanService.create_plan(wizard)`:
```
1. pool 拉取候选 → recommend(Top5) → allocate(weights) → backtest(验证)
   (recommend 规则层已剔除已重仓基金 —— 禁止重复)
2. 生成 tranches(100份 + 择时) → 存 portfolio_plan(draft)
3. 前端展示完整方案
4. 用户 confirm → 逐批建仓:
   a. 每只基金按 plan 单独写 plan_holding(累计成本/份额/平均成本), 独立核算浮盈
   b. 同时写全局 holdings(用于每日顾问整体分析), 但 plan 盈亏看 plan_holding
   c. 扣余额(used+/remaining-) → tranche 置 executed
   → status=active
5. 该 plan 基金进入每日顾问跟踪列表(顾问按 plan_holding 报该计划浮盈)
```

---

## 4. AI 提示词设计 (NewAPI)

### 4.1 AI荐基研判 (规则预筛后 Top20 → AI 挑 Top5)
```
你是基金投顾研究员。以下是【已通过量化初筛的候选基金】及各自指标:
{候选列表: code/name/type/近1年收益/最大回撤/波动率/风格}
当前市场环境:{可选: 大盘情绪/风格轮动} (由规则层提供)

任务: 挑选现阶段【最适合入场】的 3-5 只, 输出严格 JSON:

【硬约束】候选列表已剔除你已重仓的基金; 你**不得推荐任何已持有的基金**(避免重复建仓/过度集中)。
{
  "picks": [{
    "fund_code":"...", "reason":"为什么现在适合入场(人话)", 
    "risk_tip":"风险提示", "one_liner":"一句话点评"
  }],
  "overall_view":"对整个组合的综合判断(人话)"
}
要求: 只准从给定候选中选, 不得臆造基金; 理由要具体可核; 语言通俗。
```

### 4.2 长期方案解读 (配比+分批生成后)
```
你是投资理财顾问。根据以下量化结果, 为用户生成一份【长期投资方案解读】:
- 预算/风险偏好
- 选中基金及配比
- 分批计划(100份/择时)
- 回测战绩(收益/回撤/修复时长)

输出结构化人话方案: ①整体策略 ②每只基金角色(核心/卫星/压舱) 
③分批执行说明(怎么投/投几批) ④风险与最坏情况 ⑤后续跟踪要点。
禁止承诺收益; 明确"仅供参考, 不构成投资建议"。
```

### 模型选择 (复用已稳定链路)
- 荐基研判/方案解读: step-3.7-flash(主) → minimax-m3(fallback) → nemotron(兜底)
- (沿用 RFC-017 已验证的 failover 链)

---

## 5. 前端 (新增 plan 向导)

### 5.1 页面结构 `PlanWizard.vue` (一步一模块, 回归底部)
```
Step 1 预算&偏好: 预算金额 / 风险偏好(保守/稳健/激进) → 开始
Step 2 AI荐基: 展示 Top N + AI理由; 可增删勾选
Step 3 配比: 权重%(可微调) + 每只预算金额预览
Step 4 回测验证: 一次性 vs 定投 双曲线 + 指标(回撤/修复时长/盈利概率)
Step 5 分批计划: 100份拆法 + 择时信号 + 建议执行批次
Step 6 确认入场: 完整方案总览 → "确认建仓"(写持仓) 
```
- 菜单: 新增「投资方案」入口 (`/plan`), 图标/路由注册。
- 复用 axios 拦截器(响应已解包)。
- 免责声明常驻底部。

---

## 6. 与现有模块的衔接 (链接点)
| 现有模块 | 本方案如何复用 |
|---------|--------------|
| screener.screen_funds | 规则预筛层(②) |
| timing.dca_planner | 分批择时(⑤) |
| simulator + backtest | 回测验证(④, 加修复时长字段) |
| holding.simple_import | 全局 holdings 写入(⑥); 计划盈亏另行写 plan_holding 独立核算 |
| advisor_service | 建仓后自动跟踪(⑥→锦上添花) |
| adaptive(WFA) | 方案参数长期优化 |
| sim_tmp_fund | 组合基金净值按需拉取缓存思路 |

---

## 7. 开发检查清单 (每期验收)
- [ ] P0 后端: 4 新表(含 plan_holding) + FundPoolService 池机制
- [ ] P0 后端: 10 个 plan API 编排(池×2+荐基+配比+回测+任务轮询+分批+确认+列表+详情)
- [ ] P0 后端: AI 荐基提示词(msg 已就绪, 含"禁止重复/已持仓"硬约束)
- [ ] P0 前端: PlanWizard 六步
- [ ] P1: 回撤修复时长 / 定投对比指标
- [ ] P1: 确认建仓(写 plan_holding 独立核算 + 扣余额) + 计划状态机
- [ ] P1: 每日顾问接入 plan(按 plan_holding 报该计划浮盈, 自动跟踪)
- [ ] P2: 组合看板/止盈提醒/情景压力测试

→ 下一步: 开发计划(RFC-018-开发计划), 分期排期。
