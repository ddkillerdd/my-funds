# RFC-001: AI 分析增强 — 市场数据丰富 + 多模型共识

> **状态**: 规划中  
> **作者**: qiqi / AAA  
> **创建日期**: 2026-07-29  
> **关联 OPT**: OPT-001（PROJECT.md §22）  

---

## 1. 目标

提高 AI 分析质量，使分析结果更可信、可操作，从而提高用户的实际盈利率。

## 2. 现状

当前分析链路：

```
用户点击 → 抓取持仓快照 → 构造 Prompt → step-3.7-flash 单次调用 → 解析 JSON → 展示
```

存在的问题：

| 问题 | 影响 |
|------|------|
| Prompt 只含持仓数据，无市场宏观数据 | AI 不知道当前大盘在涨还是跌 |
| 单模型单次调用 | 单个模型的偏见/幻觉直接输出 |
| 温度 0.3 保守但无校验 | 建议缺乏多样性，无法交叉验证 |
| 货币基金也参与分析但无特殊处理 | 浪费渠道调用（货币基金净值波动忽略不计） |

## 3. 方案设计

### 3.1 架构变化

```
用户点击「生成分析报告」
  │
  ├── 并行抓取市场数据 ← 新增: market_data_fetcher.py
  │   ├── 沪深300 / 创业板指 近5日涨跌幅
  │   ├── 板块热度 TOP5
  │   └── 10年期国债收益率（股债性价比参考）
  │
  ├── 并行调用 3 模型分析 ← 增强: advisor_service.py
  │   ├── step-3.7-flash（当前主模型）
  │   ├── minimax-m3（综合能力强）
  │   └── nemotron-9b（轻量快，作为第三方验证）
  │
  ├── 共识合并 ← 新增: consensus.py
  │   ├── health_score → 取中位数（抗异常值）
  │   ├── action → 取多数一致
  │   └── 分歧项 → step-3.7 仲裁（仅仲裁有分歧的基金）
  │
  └── 输出最终报告（格式不变，前端不动）
```

### 3.2 新增文件

| 文件 | 职责 | 预计代码量 |
|------|------|-----------|
| `backend/services/market_data_fetcher.py` | 从东方财富/公开 API 抓取大盘指数、板块热度、国债收益率 | ~80 行 |
| `backend/services/consensus.py` | 多模型结果合并算法、分歧检测、仲裁逻辑 | ~100 行 |

### 3.3 修改文件

| 文件 | 改动内容 | 预计改动量 |
|------|----------|-----------|
| `backend/services/advisor_service.py` | `analyze()` 方法改为多模型并行；`_build_analysis_prompt()` 加入市场数据 | ~60 行 |
| `backend/scheduler/advisor_job.py` | 适配新 analyze 接口（无需改，原地升级） | 0 行 |
| `backend/api/advisor.py` | 无需改动（接口不变） | 0 行 |
| `frontend/src/views/AdvisorView.vue` | 无需改动（响应格式不变） | 0 行 |

### 3.4 市场数据抓取设计

```python
# market_data_fetcher.py 核心逻辑

def fetch_market_data() -> dict:
    """并行抓取市场数据，超时 15s 容错"""
    return {
        "market_broad": {
            "hs300": {"latest": 3800.12, "change_5d": 2.3},  # 沪深300
            "cyb": {"latest": 2200.56, "change_5d": -1.2},   # 创业板指
        },
        "sector_heat": [  # 板块热度 TOP5
            {"name": "半导体", "change_5d": 5.6},
            {"name": "新能源", "change_5d": -3.1},
            ...
        ],
        "bond_yield": {
            "cn10y": 2.15,  # 10年期国债收益率
            "us10y": 4.35,  # 美国10年期国债收益率（可选）
        },
        "fetched_at": "2026-07-29T22:00:00"
    }
```

**抓取源**：
- 指数数据：东方财富 API `push2.eastmoney.com/api/qt/ulist.np/get`
- 板块热度：东方财富板块排行 API
- 国债收益率：中国人民银行官网或英为财情

**容错**：某个源超时/失败 → 该字段标记为 `null`，不影响整体分析

### 3.5 Prompt 变化

在已有持仓数据 **之前** 插入市场数据段，让 AI 先看大盘再看持仓：

```diff
+## 当前市场环境
+- 沪深300: 3800.12 (近5日 +2.3%)
+- 创业板指: 2200.56 (近5日 -1.2%)
+- 板块热度TOP: 半导体(+5.6%), 新能源(-3.1%), ...
+- 10年期国债收益率: 2.15%
+
## 持仓概况
- 总市值: ...
```

### 3.6 多模型共识算法

```python
# consensus.py 核心逻辑

def merge_reports(reports: list[dict], report_models: list[str]) -> dict:
    """合并多个模型的分析报告"""

    # Step 1: health_score → 取中位数
    for fund_code in all_funds:
        scores = [r[fund_code] for r in reports if fund_code in r]
        merged_health[fund_code] = median(scores)

    # Step 2: action → 取多数一致
    # add/reduce/hold/watch 四种操作，出现 ≥2 次的采用
    # 如果三模型各执一词 → 标记为分歧

    # Step 3: 分歧项 → step-3.7 仲裁
    # 只让仲裁模型看分歧项的原始数据和各模型的建议
    # 仲裁 Prompt 很短，只处理分歧部分
```

**分歧仲裁 Prompt 设计**（仅针对有分歧的基金）：

```
以下基金的分析结果存在分歧，请你仲裁：
基金A: step-3.7 建议「加仓」, minimax 建议「持有」, nemotron 建议「持有」
当前该基金...
净值走势: ...
持仓占比: ...

请选择你觉得最合适的操作并说明理由（50字以内）。
```

### 3.7 耗时估算

| 步骤 | 耗时 | 是否并行 |
|------|------|---------|
| 抓取市场数据 | ~12s | 是 |
| step-3.7 分析 | ~30s | 并行 |
| minimax-m3 分析 | ~30s | 并行 |
| nemotron-9b 分析 | ~20s | 并行 |
| 共识合并 | ~2s | 串行 |
| 分歧仲裁（如有） | ~15s | 串行 |
| **总计（最坏情况）** | **~60s** | |

> NIM 渠道 40 RPM 限制：完整分析最多 4 次调用（3 分析 + 1 仲裁），远低于限制。

### 3.8 RPM 预算

| 场景 | 调用次数 | 占 RPM |
|------|---------|--------|
| 完整分析（有分歧） | 4 次 | 10% |
| 完整分析（无分歧） | 3 次 | 7.5% |
| 用户连续点 3 次 | 12 次 | 30% |
| OpenClaw cron 单次 | 4 次 | 10% |

> 即使早晚高峰各触发一次 + 用户自己点一两次，每日总调用 ≤ 20 次，远低于 40 RPM 限制。

## 4. 影响评估

| 维度 | 影响 |
|------|------|
| 数据库 | 无改动 |
| 前端 | 无改动（响应格式不变） |
| 后端 API | 无改动（接口不变） |
| 分析耗时 | 30s → ~60s（可接受，用户可等待） |
| 现有功能 | 不影响 |
| GitHub | 3 文件新增/修改 |
| 部署 | 无需重启服务（热加载） |

## 5. 回滚方案

```bash
# 方式一：单文件回滚
git checkout -- backend/services/advisor_service.py
rm backend/services/market_data_fetcher.py
rm backend/services/consensus.py

# 方式二：git revert（如果已 commit）
git revert HEAD
```

## 6. 未覆盖事项（后续 RFC）

- OPT-002: 建议效果追踪（需要新数据库表，L3 层级）
- OPT-003: PWA 离线缓存
- 多语言支持
- 用户自定义分析参数

---

## 附录 A：实现顺序建议

```
Step 1: market_data_fetcher.py + 修改 Prompt
        → 验证：单模型分析时市场数据已生效
        → 可单独部署，不依赖后续步骤

Step 2: consensus.py + 多模型并行
        → 验证：三模型结果合并正确
        → 需要 Step 1 提供市场数据

Step 3: 分歧仲裁
        → 验证：分歧基金正确识别+仲裁输出合理
        → 可选步骤，无分歧时跳过
```
