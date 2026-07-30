# Changelog

> 版本变更摘要。详细开发日志见 `DEVLOG.md`。

## [1.0.0] - 2026-07-29

### Added
- Phase 0: 环境适配部署（Python 3.12 + MySQL fund_advisor + CORS 适配）
- Phase 1: Bug 修复（货币基金净值、收益一致性、总资产偏差）
- Phase 1.2: 手动持仓录入（后端 POST/DELETE + 前端表单弹窗）
- Phase 2: AI 决策引擎（AdvisorService + NewAPI 集成 + 四大分析维度）
- Phase 3: 自动化推送（MailService + AdvisorJob + OpenClaw cron 工作日 09:00）

### Fixed
- 货币基金万份收益被当作单位净值的 Bug
- 日历日收益与仪表盘日涨跌不一致的 Bug
- 总资产被识别为字符串导致统计偏差的 Bug

### Changed
- config.py 默认值适配部署环境（Docker MySQL 容器）
- 前端端口 8200→8201，避免与后端冲突
- Dockerfile/docker-compose 端口同步修改
- 新增文件被 git 跟踪并推送至 GitHub

## [1.0.1] - 2026-07-29

### Added
- 持仓列表删除按钮（el-popconfirm 确认弹窗）
- PROJECT.md 附录 F 部署清单全部打勾（13+3 项）
- PROJECT.md §22 演进路线图
- PROJECT.md §23 项目目录说明
- docs/ 目录，规范 RFC 先行流程
- CHANGELOG.md 版本变更摘要

### Fixed
- .env 中 NEWAPI 配置被 SMTP 编辑覆盖丢失
- config.py 中 SMTP_TO 字段缺失
- config.py 缺少 env_file 配置导致 .env 不被自动加载
- docker-compose.yml.example 仍为旧端口(8000/3000)
- PROJECT.md 多处与实际代码不一致（config 默认值表、模型列表、目录树）
- PROJECT.md 中 scheduler/ 和 schemas/ 目录出现重复

### Changed
- SMTP 配置完成（QQ邮箱 465/SSL）
- 邮件推送链路验证通过（已产出测试邮件）
- NewAPI KEY 写入 git credential store，后续 push 免认证
- PROJECT.md v3.0→v3.2

## [1.0.2] - 2026-07-29

### Fixed
- NVIDIA NIM 推理模型 content=null 取不到值，AI 分析永远走 fallback
  - 修复：_call_llm() 从 content 降级到 reasoning 字段
  - 原因：step-3.7-flash/nemotron 等推理模型的回答在 reasoning 中

### Changed
- NewAPI token 因编码器升级失效，重新创建 fundadvisor-ai token
- .env NEWAPI_API_KEY 更新为新的 token
- DEVLOG 新增 2026-07-29 22:00 日志

## [1.1.0] - 2026-07-29

### Added
- 回退模型链机制：step-3.7 → nemotron-nano-9b → minimax-m3 轮流尝试
- `fallback_chain` 字段标记本次分析实际使用的模型链路

### Changed
- advisor_service.analyze() 支持传入模型列表，失败自动切换下一个
- 新增 `_is_fallback_result()` 判断 LLM 返回是否为兜底
- 保持原有 API 返回结构不变（前端无感）

## [1.3.0] - 2026-07-30

### Added
- 快捷导入功能（RFC-002）：用户只需基金代码 + 持有金额
- `POST /api/holdings/simple-import` 新 API 端点
- 前端 ImportView 新增快捷导入卡片
- docs/RFC-002-simplified-import.md 提案文档
- 自动从 latest_nav / nav_history 反算份额
- 无净值时份额标记为 0，等待定时任务补采

## [1.4.0] - 2026-07-30

### Added
- AI 顾问报告持久化：每次分析报告自动存入 DB，刷新不丢失
- 新增 `advisor_report` 表（id / report_json / model_used / created_at）
- `GET /api/advisor/report` — 获取最近报告
- `GET /api/advisor/report/{id}` — 按 ID 获取指定报告
- `GET /api/advisor/reports` — 分页列出历史报告元数据
- 前端左侧历史报告列表 + 点击加载 + 分页浏览
- `backend/models/advisor_report.py` — 报告模型
- `docs/report-persistence.md` — 持久化方案文档

### Changed
- `POST /api/advisor/analyze` 写入报告后自动清理最旧超量记录
- 后端返回时间统一转为北京时间（CST, UTC+8）
- `AdvisorView.vue` 重构为左右布局（历史侧栏 + 报告内容）
- 前后端均配 systemd 保活（`fund-advisor-backend.service` / `fund-advisor-frontend.service`）

### Fixed
- 前端刷新后报告消失
- 历史报告中时间显示为 UTC（现正确显示 CST）

### Docs
- docs/report-persistence.md — 完整 API 说明 + 清理策略 + 文件变更清单
- DEVLOG.md — 追加持久化实现记录
- CHANGELOG.md — 本次变更
