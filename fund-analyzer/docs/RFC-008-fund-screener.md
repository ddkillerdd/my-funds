# RFC-008: 荐基引擎（Fund Screener）— 从「分析持仓」到「推荐标的」

> **状态**: 提案
> **日期**: 2026-07-31
> **作者**: AAA
> **前置**: RFC-009（总纲）、RFC-007（择时）
> **优先级**: P1
> **核心价值**: 让系统回答「该买什么 + 为什么适合我 + 配多少」

---

## 一、问题

FundAdvisor 现在只分析「用户已经持有的基金」。用户真正高频的需求是 **「我想新增一笔投资，买哪只？」** —— 现有系统完全无法回答。

## 二、方案

构建 **多因子打分荐基引擎（Fund Screener）**：

```
候选池（东财基金列表/同类/热门）
   ↓ 多因子打分（全量化，防幻觉）
   ↓ 相关性互补（与现有组合）
   ↓ 规模/流动性过滤
   ↓ 风格标签
   ↓ AI 解读（LLM 只做文案，不做判断）
   ↓
推荐列表: 每只含 分数/风格/为什么适合我/建议仓位
```

## 三、打分因子（全部量化可算）

| 因子 | 权重 | 计算方式 | 数据源 |
|------|------|---------|--------|
| **动量** Momentum | 20% | 3m/6m/1y 收益的风险调整（收益÷波动）| 东财净值 |
| **质量** Quality | 20% | Sharpe×0.4 + Sortino×0.3 + Calmar×0.3 | 东财净值 |
| **回撤控制** Drawdown | 15% | 100 - max_drawdown_罚分；恢复速度快加分 | 东财净值 |
| **相关性互补** Diversify | 20% | 与现有组合平均相关越低分越高 (1-corr)×100 | 组合净值 |
| **规模/流动性** Size | 10% | 规模2-500亿最优，<2亿惩罚 | 东财详情 |
| **估值安全** Valuation | 15% | 估值分位越低越高（Phase C 起）| 东财估值 |

**总推荐分** = Σ(因子分 × 权重)。未取到某因子则权重归一化（其余因子按比例放大），保证冷启动可用。

## 四、风格标签

用净值历史做**粗略风格归因**（不依赖持仓，纯量化）：
- **关联法**：与 沪深300/中证500/创业板/纳指/白酒/新能源 等指数净值相关，找相关性最高的 → 打「大盘蓝筹/中小盘成长/科技/消费/医药」等标签
- 需要 Market Data Layer 的指数净值
- 无指数数据时 → 用波动率+动量聚类成 保守/稳健/积极/激进 风控标签

## 五、为什么适合我（可解释性）

不是给一坨基金，而是给**每个候选的适配理由**：

| 输入 | → 解释 |
|------|--------|
| 现有组合相关矩阵 | "该基金与你持有的白酒相关性 0.12，可分散集中风险" |
| HHI 集中度 | "你当前 Top1 占比 45%，建议增配低相关大类" |
| 现有组合风险水平 | "你偏好稳健，该基金波动 18% 在你的承受区间" |
| 各因子得分 | "动量 82/质量 75/回撤控制 68，综合排名第 3" |

AI 解读层 prompt 结构（Data→Concept→Thesis，借鉴 FinRobot）：
```
[量化事实卡: 各因子得分 + 相关性 + 适配理由]
→ 输出: "为什么推荐" + "注意风险" + 一句话结论
（LLM 只解释已算出的数字，不自己发明理由）
```

## 六、建议仓位（与择时/再平衡联动）

```
建议仓位 = 基准(1/候选数) × 相关性互补系数 × 择时窗口系数
```
- 相关性越低 → 仓位略高（分散价值）
- timing_score 越低 → 暂缓一次性建仓，转为定投
- 所有建议 ≤ 明确的单只上限，且输出「非投资建议」免责

## 七、数据结构（models.py 新增）

```python
@dataclass
class ScreenerFactorScore:
    factor: str          # momentum/quality/drawdown/diversify/size/valuation
    value: float
    score: float         # 0-100
    evidence: str
    weight: float

@dataclass
class RecommendedFund:
    fund_code: str
    fund_name: str
    fund_type: str
    total_score: float           # 0-100
    factor_scores: List[ScreenerFactorScore]
    style_tag: str               # 大盘蓝筹/科技成长/消费/...
    correlation_with_portfolio: Optional[float]
    suggested_ratio_pct: float
    current_timing: Optional[EntryRecommendation]   # 联动 RFC-007
    ai_explanation: str
    data_quality: str
    disclaimer_note: str = "仅供参考，不构成投资建议"

@dataclass
class ScreenerResult:
    generated_at: str
    candidates_scanned: int
    portfolio_context: Dict       # 现有组合相关性/集中度
    recommendations: List[RecommendedFund]  # 按 total_score 降序
    notes: List[str]
```

## 八、API

```
POST /api/advisor/funds/recommend     # 基于现有组合推荐
POST /api/advisor/funds/recommend?category=指数&exclude=161725   # 指定类别
GET  /api/advisor/funds/{code}/screener-score   # 单只打分明细
```

## 九、实现阶段

### Phase C（P1，先决）：Market Data Layer
- 抓沪深300/创业板/中证500 + 各风格指数净值（用于风格归因）
- 抓候选基金净值 + 规模/类型详情

### Phase D（P1）：Screener v1
- `engine/screener.py` 六因子打分
- 指数关联风格归因
- 与现有组合相关性互补

### Phase E（P2）：完整闭环
- 荐基 → 择时 → 目标权重 → 再平衡建议

## 十、验收标准

| 测试 | 期望 |
|------|------|
| 输入组合=白酒+纳指 | 推荐中低相关大类，打「大盘/价值」风格，避免再推白酒类 |
| 候选 500 只 | 打分排序稳定，Top10 解释完备 |
| 无指数数据（冷启动） | 风格归因降级为波动率聚类，仍能打分 |
| LLM 全挂 | 荐基排序照常输出，ai_explanation=空 |
| 内存 | candidate 净值分批 1 万条以内处理，峰值 <200MB |

## 十一、参考

- JoinQuant/聚宽：多因子选基、风格归因、同类排名
- Morningstar 风格箱（大盘/中盘/小盘 × 价值/成长）：灵感但用净值近似
- Fama-French 多因子（动量/质量/规模）：因子选择依据
- Risk Parity：相关性互补的仓位分配依据
