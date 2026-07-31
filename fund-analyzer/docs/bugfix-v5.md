# Bugfix v5.0 — 代码审查发现的所有 Bug

审查范围：`fund-analyzer/engine/` + `fund-advisor/backend/` + `fund-advisor/frontend/`

## Bug 列表

### 🔴 Bug 1: 前端 actions 前两条不显示 fund_name（已修复）
- **位置**: `advisor_service.py` `_report_to_api_json` L284
- **原因**: 组合级调仓建议（rebalance_suggestions）的 `fund_name` 原来写死 `""`
- **影响**: 前端操作建议列表前两条只显示 `减仓`/`增持` 但没有基金名
- **修复**: 从 `per_fund_diagnosis` 查找基金名填入；`GET /report/{id}` 也做后处理补全

### 🔴 Bug 2: concerns/risks 带证据引用括号（前端已修复，后端部分修复）
- **位置**: `advisor_service.py` `_report_to_api_json` clean_risks
- **原因**: 后端正则只匹配含 `=` 的括号 `（xxx=1.5）`，不匹配纯数字括号 `(42.68%)` 和 `(-0.0623)`
- **影响**: 前端 `concerns` 显示冗余证据引用
- **修复**: 前端 `cleanEvidence()` 用更宽正则覆盖所有含数字或等号的括号

### 🟡 Bug 3: portfolio_diagnosis 字段在 API JSON 中为空
- **位置**: `advisor_service.py` `_report_to_api_json` L560-570
- **原因**: `_report_to_api_json` 中 `portfolio_diag["overall_assessment"]` 取 `pd.health_label`，但前端用的 key 是 `overall_health_score` 和 `overall_health_label`——不一致
- **影响**: 前端"组合诊断"区域 `overall_assessment` 显示空
- **修复**: 统一字段名

### 🟡 Bug 4: analyzer.py `_analyze_4_views` 日志中文含省略号
- **位置**: `analyzer.py` L385 `logger.info(f"Tre…ren {trend_model} failed...")`
- **原因**: `…` 是 Unicode U+2026，不报错但可能在某些编码环境下导致问题
- **影响**: 无实际功能影响，但不规范
- **修复**: 改为 ASCII `Trend model`

### 🟡 Bug 5: `import re` 在循环内
- **位置**: `advisor_service.py` `_report_to_api_json` clean_risks 循环内 `import re`
- **原因**: 每次 iteration 都会执行 import 语句（虽然 Python 有缓存但仍是代码异味）
- **影响**: 无功能影响，但代码不规范
- **修复**: 移到文件顶部

### 🟡 Bug 6: `_report_to_api_json` 后端 risks 清洗正则与前端不同步
- **位置**: `advisor_service.py` clean_risks 正则只匹配 `=`，不匹配纯数字
- **原因**: 后端正则 `r'[（(][^）)]*=[^）)]*[）)]'` 远比前端的窄
- **影响**: 后端存入 DB 的 `concerns` 和 `v3_risks` 仍然带括号
- **修复**: 后端也用宽正则

### 🟢 Bug 7: `GET /report` (latest) 没有补全空 fund_name
- **位置**: `api/advisor.py` `get_latest_report`
- **原因**: 只有 `GET /report/{id}` 做了 fund_name 补全，`GET /report` (latest) 没做
- **影响**: 首次加载最新报告时前两条 action 可能不显示基金名
- **修复**: 提取公共函数 `_patch_report_actions`，两个端点都用

### 🟢 Bug 8: `validate_diagnosis_json` 从未被调用
- **位置**: `llm_client.py` `validate_diagnosis_json`
- **原因**: 定义了但 analyzer.py 从未使用
- **影响**: 无 bug，但死代码
- **修复**: 在 debate 和 view parse 后调用验证，如果有必要的话。暂不修，留 TODO

### 🟢 Bug 9: `completeness` 计算逻辑有误
- **位置**: `analyzer.py` L740-760
- **原因**: `total_computed` 和 `total_expected` 用同一个值，`completeness_pct` 永远是 100%
- **影响**: completeness 一直是 100%，不准确
- **修复**: 暂不修（不影响用户体验），留 TODO

### 🟢 Bug 10: `actionLabel` 缺少 `exit`/`enter` 映射
- **位置**: `AdvisorView.vue` actionLabel
- **原因**: LLM 可能返回 `exit`/`enter` 等未映射的 action 值
- **影响**: 显示原始英文值
- **修复**: 加 fallback `return action`（已有）