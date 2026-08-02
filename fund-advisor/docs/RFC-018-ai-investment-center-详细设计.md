# RFC-018 · AI投顾"长期投资方案中心" — 详细设计

> 版本: v0.1 (2026-08-03) | 依赖: 调研 + 架构
> 定位: 开发准备, 可照此直接写代码。复用现有引擎(不重造)。

---

## 1. 数据表设计 (SQLAlchemy, 新增 3 表)

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
    risk_profile = Column(String(20), default="balanced")  # conservative/balanced/aggressive
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
    units = Column(Integer)               # 应投份数(每份 = total_budget/100)
    nav_signal = Column(String(30))       # 择时信号: buy/observe/avoid
    plan_date = Column(Date)              # 建议执行日
    status = Column(String(20), default="pending")  # pending/executed
    executed_at = Column(DateTime, default=None)
    amount = Column(Numeric(14,2), default=None)    # 实际投入金额
```

---

## 2. 算法设计

### 2.1 每份金额 & 分批(核心公式)
```
unit = total_budget / 100            # 每份金额
# 分 100 份, 每批建议份数由择时信号决定:
#   - 估值低分位(机会区) → 一批 10-20 份 (多投)
#   - 估值中性         → 一批 5-10 份 (正常)
#   - 估值高/avoid     → 0 份, 暂停(耐心等)
# 配比落地: fund_i 的金额 = 批次金额 × weight_pct_i
```

### 2.2 配比权重(复用 + 风控约束)
- 基线: `suggested_ratio_pct`(screener 现成)。
- 风控约束:
  - 单只上限 25%, 下限 5%; 合计 = 100%。
  - 高风险类(商品/行业/高波动)按 risk_profile 归一缩放:
    - conservative: 高风险×0.5, 债券/稳健权重上浮
    - aggressive: 高风险×1.2
- 归一化: `w_i / Σw_i × 100` 保证总和 100%。

### 2.3 回测验证(复用 simulator)
- 输入: `{funds: [{code, amount = total_budget×weight}], windows, target_vol, friction}`
- 输出直接映射 simulator 现有返回 + 新增:
  ```
  max_drawdown_recovery_days  # 最大回撤修复时长(借鉴雪球)
  win_rate                    # 盈利概率(若引擎可算)
  ```
- 双路径: 一次性(全部按初始配比) vs 每月定投(每期等额) → 对比展示(借鉴 Wallible)。

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
2. 生成 tranches(100份 + 择时) → 存 portfolio_plan(draft)
3. 前端展示完整方案
4. 用户 confirm → 逐批建仓(调 simple_import 扣余额) → status=active
5. 该 plan 基金进入每日顾问跟踪列表
```

---

## 4. AI 提示词设计 (NewAPI)

### 4.1 AI荐基研判 (规则预筛后 Top20 → AI 挑 Top5)
```
你是基金投顾研究员。以下是【已通过量化初筛的候选基金】及各自指标:
{候选列表: code/name/type/近1年收益/最大回撤/波动率/风格}
当前市场环境:{可选: 大盘情绪/风格轮动} (由规则层提供)

任务: 挑选现阶段【最适合入场】的 3-5 只, 输出严格 JSON:
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
| holding.simple_import | 确认建仓(⑥) |
| advisor_service | 建仓后自动跟踪(⑥→锦上添花) |
| adaptive(WFA) | 方案参数长期优化 |
| sim_tmp_fund | 组合基金净值按需拉取缓存思路 |

---

## 7. 开发检查清单 (每期验收)
- [ ] P0 后端: 3 新表 + FundPoolService 池机制
- [ ] P0 后端: 6 个 plan API 编排
- [ ] P0 后端: AI 荐基提示词(msg 已就绪)
- [ ] P0 前端: PlanWizard 六步
- [ ] P1: 回撤修复时长 / 定投对比指标
- [ ] P1: 确认建仓扣余额 + 计划状态机
- [ ] P1: 每日顾问接入 plan(自动跟踪)
- [ ] P2: 组合看板/止盈提醒/情景压力测试

→ 下一步: 开发计划(RFC-018-开发计划), 分期排期。
