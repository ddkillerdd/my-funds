# RFC-017 自适应策略参数优化（Walk-Forward · 甲方案 · 半自动模式 X）

- **状态**: 已批准实现
- **版本**: 1.0.0
- **日期**: 2026-08-02
- **作者**: AAA (代理) / qiqi (负责人)
- **关联代码**:
  - `fund-analyzer/engine/strategy_config.py` — 策略参数配置层 + 风险分类
  - `fund-analyzer/engine/adaptive_optimizer.py` — WFA 自适应调参引擎
  - `fund-advisor/backend/models/adaptive_proposal.py` — 推荐记录表
  - `fund-advisor/backend/models/strategy_override.py` — 生效参数表
  - `fund-advisor/backend/services/adaptive_service.py` — 桥接 + 异步任务 + 采纳/否决
  - `fund-advisor/backend/api/adaptive.py` — REST API
  - `fund-advisor/backend/services/advisor_service.py` — 报告侧生效参数注入
  - `fund-advisor/frontend/src/views/AdaptiveView.vue` — 前端"自适应优化"页
- **唯一目标**: **求稳 + 防过拟合**。用历史数据为每个风险类别找出稳健的策略参数，但只在"能证明比保守默认更好"时才建议启用，且必须由用户确认才进入实战。

---

## 1. 背景与设计原则

### 1.1 为什么需要自适应参数

现有决策内核 `build_position_action` 的参数 `target_vol=0.15`、`friction_band_pp=5.0` 是**硬编码默认值**，对所有基金、所有市况同一套。问题：

| # | 问题 | 说明 |
|---|------|------|
| P1 | 一刀切 | 高波动军工基金和低波动债基用同一目标波动率，风控失配 |
| P2 | 参数凭经验 | 0.15/5.0 是拍脑袋默认，从未用数据验证是否最优 |
| P3 | 无证据闭环 | 从没有人问："换一组参数，历史回测是否真的更好？" |

### 1.2 甲方案（已拍板）

- **优化目标**: 最大化夏普比率 + 分类动态回撤硬约束（低/中波动 ≤15%，高波动 ≤20-25%）。注意：**不是**"稳定盈利"——"稳定盈利"是结果不是可优化的目标函数。
- **只调两个旋钮**: `target_vol` 与 `friction_band_pp`。决策内核公式**不动**（防过拟合，避免对公式层做无谓的过度优化）。
- **统一内核 + 按量化特征聚类分化**: 所有基金共用同一套 `build_position_action`，但按年化波动率分为低/中/高三类，每类独立找参数。
- **模式 X（半自动）**: 系统产出"已验证好参数 + 样本外证据"作为推荐，用户确认才写入实战；用户有最终否决权。

### 1.3 三大约束（防过拟合核心）

1. **样本外验证**: 参数在训练段选出，必须在**从未参与选参的测试段**盲测通过才算数。
2. **必须优于"什么都不做"**: 自适应参数若连本类**保守默认**都跑不赢，采纳无意义，诚实拒绝。
3. **历史长度克制**: WFA 只取最近一段（默认 600 交易日 ≈ 2.5 年，可配 400~1200）。不用无限长历史（幸存者偏差 + 市场结构漂移会让旧数据误导）。

---

## 2. 架构

### 2.1 参数分离（报告侧 vs 模拟侧解耦）

```
strategy_config.py  (配置层)
├── FundStrategyConfig  dataclass: target_vol / friction_band_pp / risk_class / source / proposal_id / note
├── RiskClass: low=低波动 / medium=中波动 / high=高波动
├── classify_fund(navs) -> risk_class   # 按最近一年日收益年化波动率聚类: <15%低 / <25%中 / ≥25%高
└── class_default(cls) -> FundStrategyConfig   # 各类保守默认(未采纳时兜底)
```

- **报告侧（analyzer）**: 读 `approved` 参数（经用户确认的 override）；无则用 `class_default` 保守默认。
- **模拟侧（simulator）**: 读 `explored` 参数，自由跑 WFA 探索——**研究报告不带动实盘**。

### 2.2 数据落库

| 表 | 作用 | 关键字段 |
|----|------|---------|
| `adaptive_proposal` | 每次 WFA 产出的推荐记录 | risk_class, target_vol, friction_band_pp, 样本外指标(excess/mdd/wfe), passed, status(pending/approved/rejected) |
| `strategy_override` | 某风险类别**当前实际生效**参数 | risk_class(unique), target_vol, friction_band_pp, source=approved, proposal_id |

**安全规则**: 只有 `passed=True` 的 proposal 才能被 `approve`；只有 `approve` 才会写 `strategy_override`。pending/rejected 一律不影响实盘。

### 2.3 异步任务

WFA 是 CPU 密集（数十秒~分钟），不能在请求线程同步跑：

- `POST /api/adaptive/run` 用**后台 daemon 线程**执行，立即返回 `task_id`。
- 后台线程使用**独立数据库 Session**（避免与请求线程共享 SQLAlchemy session）。
- 前端以 3s 间隔轮询 `GET /api/adaptive/tasks/{task_id}`。

---

## 3. WFA 算法（adaptive_optimizer.py）

```
optimize_fund_class(funds, risk_class=None, train_ratio=0.60, min_train_days=250, min_test_days=100, ...)
```

1. **自动分类**: `classify_fund` 按年化波动率聚类（或显式指定 risk_class）。
2. **切段**: 公共历史按 60%/40% 切训练段 / 测试段。不足 `min_train + min_test = 350` 天则诚实返回"数据不足"，**不硬造参数**。
3. **训练段网格搜索**: 在 `target_vol × friction` 网格上回测，选训练段表现最优的参数。用较短评估窗口（120 交易日）只做**相对排序**以提速。
4. **样本外盲测**: 用选出的参数在**测试段**回测，得样本外超额/回撤/夏普。
5. **稳健性校验**（超出则 `passed=False`）:
   - 样本外相对**保守默认**的增益 > 0（跑不赢"什么都不做"就拒绝）；
   - 样本外最大回撤 ≤ 该风险类别上限（低/中 15%、高 20-25%）。
   - **样本外夏普**作为稳健性代理展示（不再用 "训练超额/测试超额" 比值——那是经典 WFE，但我们的切段口径会让绝对超额失真，曾出现 28x 假象）。
6. **推荐**: `passed=True` → 推荐采用；`passed=False` → 推荐回到保守默认（保留证据供查看）。

### 默认网格

```
target_vol ∈ [0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25]
friction   ∈ [3, 5, 7, 10]
```

（前端"开始优化"可传自定义 `tv_grid` / `fr_grid` 覆盖。）

---

## 4. REST API（api/adaptive.py，prefix `/api/adaptive`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/run` | 异步发起 WFA（可选 fund_codes / lookback_days / tv_grid / fr_grid），返回 task_id |
| GET | `/tasks/{task_id}` | 轮询任务状态（status: pending/running/done/error + progress） |
| GET | `/proposals` | 列推荐（可选 status 过滤） |
| POST | `/proposals/{id}/approve` | 采纳（passed=False 会被拒），写入 override |
| POST | `/proposals/{id}/reject` | 否决 |
| GET | `/overrides` | 当前生效参数 |
| POST | `/overrides/{class}/reset` | 撤销某类生效参数（回退保守默认） |

### 报告侧注入（advisor_service.py）

`_analyze_v3` 创建 `Analyzer` 前，为每个持仓基金调用 `AdaptiveService.get_active_config(fund_code)`：

```python
cfg = adaptive_svc.get_active_config(h.fund_code)   # 有 approved override → 用之；无 → 保守默认
analyzer = Analyzer(config, strategy_configs={h.fund_code: cfg, ...})
```

报告附加 `adaptive_strategy` 字段，透明展示每个基金实际用的风险类别与参数来源。

---

## 5. 性能与体验

- **单次 WFA 耗时**: 6 组小网格 ≈ 25s（600 天×3 基金）；32 组默认全网格 ≈ 75s。
- **异步设计**: 用户点"开始优化"立即拿到任务，不必干等；完成后推荐落表。
- **训练段提速**: 网格搜索用 120 交易日的评估窗口做相对排序，显著减少全段回测开销。
- 临时拉取的基金（483 天）也可参与 WFA，但可能因训练段不足触发"数据不足"防御——这是**有意的保守行为**。

---

## 6. 边界与已知取舍

| 项 | 说明 |
|----|------|
| 任务注册表为内存态 | 后端重启后进行中的任务消失（结果已落库不受影响） |
| 临时基金不污染主库 | WFA 只读，不改 `fund_nav_history`；临时表仍按模拟模块规则清理 |
| 与 RFC-012 互补 | RFC-012 校准"置信度/强调"层（不碰因子层）；RFC-017 调**参数层**（target_vol/friction），两者不冲突 |
| 判定口径 | 以"相对保守默认的增益"为准，不用绝对超额（规避 warmup/窗口干扰造成的绝对假象） |

---

## 7. 端到端验证记录（2026-08-02）

- [x] 引擎单测: 300 天数据 → 诚实"数据不足"返回保守默认（0.0s）
- [x] 引擎真实数据: 650 天×3 基金 → 训练选 0.25/10, 样本外增益 -0.43pp → passed=False, 推荐回默认 0.15
- [x] API 异步任务: `POST /run` → 后台线程 → `GET /tasks` done
- [x] 安全护栏: passed=False 的 proposal `approve` 返回 400 拒绝
- [x] 采纳链路: passed=True proposal → approve → `strategy_override` 写入 → `get_active_config` 返回 approved 参数
- [x] 清理: 测试残留 override 已 reset、测试 proposal 已 reject
- [x] 前端: AdaptiveView.vue 编译通过（vite HTTP 200），路由/菜单已注册
