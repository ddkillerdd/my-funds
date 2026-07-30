# Bug Report: v2.0.2 第三次测试——核心瓶颈发现

## 测试时间
2026-07-30 14:18-14:20

## 发现的核心问题

### Bug 8: step-3.7-flash 生产环境可用性严重下降

| 测试次 | 成功 | 超时 | 失败率 |
|--------|------|------|--------|
| v2.0.1 (14:10) | 2 | 2 | 50% |
| v2.0.2 (14:18) | 0 | 2 | 100% |

**现象**: step-3.7-flash 前两次测试时 3.4s 完成，而现在 45s 超时率高达 100%
**推测原因**: NVIDIA NIM 免费 tier 在高峰期性能衰减明显。NewAPI 有其他服务使用。
**结论**: 不能依赖 step-3.7-flash 作为唯一 Step1 分析模型。

### 修复方案

**策略变更: step-3.7 超时 → 自动切换备选模型 (nemotron-nano-9b)**

之前: step-3.7 超时 → `_fund_fallback()` 纯数字推算（质量大幅下降）
现在: step-3.7 超时 → nemotron-nano 再试 → 再失败才降级

nemotron-nano 实测:
- 延迟: 18s（稳定）
- JSON 输出: 标准
- temperature=0 时 JSON 可靠

总调用次数: 4 只基金每个最多 2 次 LLM 调用 = 4~8 次
总耗时: 最佳 4×5s + 间隔 = 26s，最坏 4×(45s+18s+间隔) = 260s

### 影响
- 分析总耗时可能上到 4-5 分钟（如果 step-3.7 全部超时）
- 每分钟最多 1 次分析（考虑 NewAPI 的其他服务使用）
- 前端 max-time 设为 600s

### Bug 9: Step2 minimax-m3 降级后返回格式不一致

**现象**: minimax-m3 也超时（45s级），降级后 `synthesis` 返回的 dict 里 `actions` 可能是字符串而非列表
**修复**: `_step4_assemble` 加 `isinstance(list)/isinstance(dict)` 防御

## 已修复

| Bug | 描述 | 修复 |
|-----|------|------|
| 1,7 | Step1 解析/降级缺少字段 | 标准化后补齐默认值 |
| 2 | long_return_pct 不存在 | 趋势函数返回默认值 |
| 4 | 超时过长 | 120→45s |
| 8 | step-3.7 不可用 | 加备选模型 nemotron-nano |
| 9 | Step2 降级 actions 类型错误 | 类型防御 |
