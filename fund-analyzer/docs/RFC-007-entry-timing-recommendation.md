# RFC-007: 基金入场时机推荐系统

> **状态**: 提案（原设计补盘 + 服务器约束强化）
> **日期**: 2026-07-31
> **作者**: AAA
> **前置**: RFC-009（总纲）、RFC-005（多模型辩论）、RFC-006（分析质量）
> **优先级**: P0（直接回应「不知道何时入场」的痛点）
> **实现路径**: Phase B 先上纯 NAV 技术择时（无外部依赖），Phase C 再补估值

---

## 一、问题

用户持有/关注基金后，核心痛点不是「该不该持有」，而是 **「现在这个点位能不能买？该一次买还是定投？」**

现有 FundAdvisor 只做「已持仓分析」，完全没有「择时/入场」能力。

## 二、方案总览

集成 6 大择时流派，输出一个可解释的时机评分：

```
择时评分 = 估值分 × 0.25
        + 技术分 × 0.25
        + 趋势分 × 0.20
        + 情绪分 × 0.10
        + 回撤位置 × 0.20   (风险位置，越高越安全)

输出:
  timing_score: 0-100
  window: now_entry | staged_entry | wait | avoid
  dca_suggestion: { enabled, plan, frequency }
  risk_gate: 是否触发「当前不追高」的硬性风控
```

## 三、六大模块设计

### 3.1 估值模块（Phase C，需 Market Data Layer）

| 数据 | 来源 | 信号 |
|------|------|------|
| 指数 PE/PB 历史分位 | 东财指数估值 | ≤20%分位=低估(all-in区)；20-40%=偏低；40-60%=中性(定投区)；60-80%=偏高(减码)；>80%=高估(回避) |
| 同类基金平均收益 | 排名接口 | 相对同类位置 |

模型：`PePercentileModel` — 对指数基金，用对应指数估值分位；对主动基金，用历史净值分位。

**数据源方案（5 选 1）**：
1. ~~akshare~~（未装，300MB+，反爬不稳）❌
2. **东财指数估值接口**（推荐，`index.eastmoney.com` PE/PB 系列）✅ 首选
3. 聚宽/米筐 API（需 token，外部依赖）⚠️
4. 本地 NAV 反推（用净值历史最长的分位近似）✅ 兜底
5. 手动录入（太繁琐）❌

### 3.2 技术模块（Phase B，纯 NAV 即可算）

**六因子打分（参考海龟+均线系统，0-60 分原始分）**：

| 因子 | 计算 | 加分/扣分 |
|------|------|-----------|
| MA 排列 | MA5/MA20/MA60 多头 | 多头+10 / 空头-10 |
| 净值 vs MA20 | 偏离度 | 0~+5%（温和）加分；>+10%扣分（乖离过大）|
| RSI(14) | 动量 | 40-60 健康+5；>70 超买-5；<30 超卖+5（布局）|
| MACD | 金叉/死叉 | 金叉+5 / 死叉-5 |
| 回撤位置 | 当前回撤占最大回撤 | >50% 释放+5；<20% 高位-5 |
| 连涨/跌 | 情绪脆弱度 | 连涨≥5天-5（追高风险）；连跌≥5天+5（超跌）|

`technique_score = max(0, min(100, raw * 100/60))`

**输出**：`momentum_score`、`bollinger_zone`（上轨/中轨/下轨）、是否处于「回调至支撑」买点。

### 3.3 趋势模块（复用 quant.py）

直接用现有 `TrendIndicators`：
- `trend_direction == up` 且 `trend_strength >= 70` → 强趋势，可顺势
- `down` → 不接飞刀，等企稳

### 3.4 情绪模块（Phase C，可选）

东财成交额 / 新发基金热度 / 北向资金（若可取）。数据不可得则权重归零并标注。「别人贪婪我恐惧」的逆向信号。

### 3.5 回撤位置模块（Phase B）

```
risk_pos = 1 - (current_drawdown / max_drawdown)   # 0=还在地板, 1=接近新高
drawdown_score = risk_pos × 100
```
- `risk_pos < 0.3`：还在深坑，可分批买入
- `0.3~0.7`：中性，定投
- `>0.7`：接近新高，追高风险大 → 减分

### 3.6 定投模块（Phase B）

**两种模式**：
| 模式 | 触发 | 逻辑 |
|------|------|------|
| 均线成本法 | `nav < MA200 × (1-θ)` | 逢跌加码，θ=5%常规/10%深度 |
| 估值定投法 | `估值分位 < 50%` | 低位多投，高位少投/停投 |

输出：`dca_enabled`、当前建议每次金额（按用户可投预算百分比）、频率（周/双周/月）。

---

## 四、硬性风控（risk_gate）

任何模型都不得让用户在高危位置一次性重仓：
- `估值分位 > 80%` 且 `nav > MA20×1.08` → `avoid`（强制不买）
- `current_drawdown > 25%`（指数）→ 提示「深跌中，等企稳信号或小额分批」
- 单次建议仓位 ≤25%（与 RFC-006 一致）

---

## 五、数据结构（models.py 新增）

```python
@dataclass
class TimingFactor:
    name: str              # 估值/技术/趋势/情绪/回撤
    score: float           # 0-100
    signal: str            # bullish/neutral/bearish
    evidence: str          # 具体数值引用
    weight: float

@dataclass
class EntryRecommendation:
    fund_code: str
    fund_name: str
    timing_score: float          # 0-100
    window: str                  # now_entry/staged_entry/wait/avoid
    factors: List[TimingFactor]
    dca: Optional[DCARecommendation]
    risk_gate: Optional[Dict]    # {blocked: bool, reason: str}
    confidence: float
    ai_summary: str              # LLM 一句话解读（可选）
    data_quality: str            # 数据完整性
```

## 六、LLM 参与方式（克制）

**核心评分 100% 量化**（估算/技术/趋势/回撤全是 Python），LLM 只做「解读」：
- prompt 结构：`量化时机事实卡(必读) → 输出一句"为什么现在/不现在是好时机" + 风险提示`
- 不作为评分依据，防止幻觉污染数字
- LLM 失败 → 直接给量化评分，无 AI 解读

## 七、实现阶段

### Phase B（P0，纯 NAV，立即可做）
- `engine/timing.py`：技术/趋势/回撤/定投模块
- `EntryRecommendation` 数据类
- API：`/api/advisor/recommend/{fund}/timing`

### Phase C（P1）
- Market Data Layer 注入估值分位
- 单只基金入口时机已完备

### Phase D（P1）
- 与 RFC-008 荐基联动：荐基给出候选 → 择时给出「哪个先买」

---

## 八、验收标准

| 测试 | 期望 |
|------|------|
| 白酒 161725（深回撤） | 回撤位置分高, window=staged_entry, dca=可启动 |
| 纳指 018044（新高附近） | 追高风险 flag, window=wait/staged, risk_gate 提示别重仓 |
| 无外部数据（冷启动） | 估值权重归零, data_quality=partial, 仍能技术择时 |
| 全部 LLM 挂 | 择时评分照常输出, ai_summary=空 |

## 九、参考

- 海龟交易法则：趋势跟随 + 仓位控制
- 均线定投法（懒人理财常见策略）：MA200 基准
- 估值定投 / 沪深300 估值分位定投研究
- JoinQuant 择时因子库
