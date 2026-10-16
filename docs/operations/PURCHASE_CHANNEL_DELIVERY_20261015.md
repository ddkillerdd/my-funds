# 渠道与费用第二轮：只读查询及安全邮件预览

任务：`MF-PURCHASE-GATE2-20261015-01`。状态：`PASS_LOCAL_ONLY`，不是上线回执。

## 1. 本阶段交付及现状

在第一轮渠道门禁上补齐两个只读入口和页面展示，不重做模型、净值历史或持仓模块。

- `GET /api/advisor/purchase-options/public`：只查询有效持仓中当前四只基金的公开页面。页面须用户手动点击，不自动查询、不登录投资账户。
- `GET /api/advisor/report/{report_id}/mail-preview`：读取既有报告，重新读取跨平台实际支出和已有渠道配置，输出确定性HTML及最终动作，不生成报告、不调用模型、不发送邮件。
- 顾问页面加入独立的公开渠道卡片；旧报告、未知费率、暂停申购和账户未核验明确区分。
- 第一个入口不能给第二个入口提供账户资格证明；公开信息不自动写入渠道配置。

第一轮说明保留：`E:\myfund11111\docs\operations\PURCHASE_CHANNEL_GATE_20261015.md`。本文件不是覆盖或替代旧回执。

本地基线HEAD：`ccab61e01407e2b28409b2a56efef010ee81073f`。未提交、未推送。

## 2. 精确文件范围

本轮编辑或新建白名单（11项，不含第一轮其余文件）：

1. `E:\myfund11111\fund-advisor\backend\api\advisor.py`
2. `E:\myfund11111\fund-advisor\backend\services\purchase_channel_service.py`
3. `E:\myfund11111\fund-advisor\backend\services\decision_delivery_service.py`
4. `E:\myfund11111\fund-advisor\backend\services\public_purchase_source.py`
5. `E:\myfund11111\fund-advisor\backend\tests\test_purchase_delivery_preview.py`
6. `E:\myfund11111\fund-advisor\backend\tests\test_public_purchase_source.py`
7. `E:\myfund11111\fund-advisor\frontend\src\views\AdvisorView.vue`
8. `E:\myfund11111\fund-advisor\frontend\src\components\PublicPurchaseOptions.vue`
9. `E:\myfund11111\fund-advisor\frontend\src\utils\purchaseChannel.js`
10. `E:\myfund11111\fund-advisor\frontend\tests\purchase-channel-ui.test.mjs`
11. `E:\myfund11111\docs\operations\PURCHASE_CHANNEL_DELIVERY_20261015.md`

第一轮另5项仍在工作区，若将来整体发布必须一起审查；不因此取得提交或部署授权：

- `E:\myfund11111\fund-advisor\backend\services\execution_policy.py`
- `E:\myfund11111\fund-advisor\backend\tests\test_advisor_execution_policy.py`
- `E:\myfund11111\fund-advisor\backend\tests\test_purchase_channel_policy.py`
- `E:\myfund11111\fund-advisor\frontend\src\components\PurchaseCheck.vue`
- `E:\myfund11111\docs\operations\PURCHASE_CHANNEL_GATE_20261015.md`

上述合计16项是本功能累计审查范围，不允许 `git add .`。

## 3. 算对的定义与最小夹具

只使用虚构基金代码、虚构平台和支付方式构造本地测试。

1. 总付款20元、申购费率0.15%：净申购额 `20 / (1 + 0.15 / 100)` 四舍五入到分为19.97元，费用为0.03元；不是净投入20元再加手续费。付款先向下到分，不能突破日20/月200。
2. 本月其他平台实际已付197元，当前报告原允许20元：发送前只读复算最多3元，不读取或恢复原始候选50元。
3. 原报告已拦截，即使异常数据还残留正数，也不得被发送前复算放行。
4. 费率未知、账户资格未确认、额度未知、过期或跨日、未来时间、分析降级、预算读取失败：零付款；没有有效证据不等于零手续费或无限额。
5. 数据库创建时间按既有UTC合同转上海时间；报告同日且不超过30分钟，渠道证据同日且不超过30分钟；预览正向金额限制在工作日14:00至14:45之前。法定交易日仍由原OpenClaw交易日门禁负责，本接口不自称法定交易日判断器。
6. `True`不是1元；NaN/Infinity不作为有效金额；异常门禁结构拒绝。多条正向候选的纯预览不会输出多个买入；真实路由复用原单日单只执行策略进一步收紧。
7. 未核验赎回费和持有批次的负向动作只输出安全摘要，不伪装成准确卖出到账金额；不改持仓或原策略参数。
8. 公开费率表中划线原价被排除，`|0.06%`识别为0.06%；同格存在两个可见费率则未知；认购费、赎回费不能误当申购费。
9. 所有动态HTML文本转义，公开链接仅由4个允许代码构造；不插入模型自由HTML或原始买入理由。

红测试证据：新增公开优惠价分隔符和布尔金额夹具后，修复前`2 failed`、退出码1；修复后均通过。只读预览入口首次缺失时另有404红测试；均为本地合成证据，不是生产失败复现。

## 4. 自动公开查询的真实边界

固定来源：`https://fundf10.eastmoney.com/jjfl_{code}.html`（天天基金第三方销售页面，不是支付宝账户接口）。单次每代码GET、不带凭据、不跟随跳转、不自动重试；每请求超时5秒、响应上限500000字节；当前最多4只。不增加依赖。

2026-10-15 21:04上海时间，修复后单轮真实公开来源验收：

| 基金代码 | 公开状态 | 小额申购费率 | 公开起购额 |
| --- | --- | --- | --- |
| 013308 | 开放 | 0.06% | 10元 |
| 022430 | 开放 | 0.12% | 10元 |
| 270042 | 暂停 | 0.13% | 2元 |
| 018044 | 暂停 | 0% | 10元 |

这张表是当次抓取快照，不是持续有效的买入建议。所有结果均 `evidence_scope=public_only`、`account_eligible=null`、`daily_remaining_rmb=null`、`payment_rmb=0`。

公开页面的日上限不等于用户账户剩余额度，公开开放不保证当前账户可申购；0申购费不等于免管理/托管/销售服务/赎回费用。不得为了“可以下单”伪造账户确认、旧截图时间或付款方式。

## 5. 数据和接口影响

- 无数据库schema、迁移、模型表结构、依赖或环境变量变更。
- 新增2个GET；无新写API，无新增定时任务，无自动报告/邮件触发。
- 报告JSON中的 `purchase_check` 增补账户核验复查所需字段：purchase_status、account_eligible、evidence_scope、fee_mode、min_purchase_rmb、daily_remaining_rmb。旧报告不迁移、不改写，也不升级为可执行。
- 沿用第一轮已有AppConfig配置读取约定 `purchase_channel_quotes_v1`，本阶段不创建、不写这个键。不存在或不可靠时正向金额为0。
- 页面查询只使用有效持仓代码，不把持仓金额、成本、收益或个人账户数据传给公开来源。

## 6. 本地验收环境与命令

Python：`E:\myfund11111\fund-advisor\.venv\Scripts\python.exe`，3.12.13。Node：`E:\NOdeJs1111111\node.exe`，24.15.0。现有依赖，不安装。

以下是离线合成测试命令，不含生产SSH、生产API、模型推理、邮件发送或真实数据操作：

```powershell
# 设置虚构测试环境，数据库、模型及邮件均指向不可用的本地端口。
Set-Location -LiteralPath 'E:\myfund11111\fund-advisor'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:DB_HOST = '127.0.0.1'
$env:DB_PORT = '1'
$env:DB_USER = 'synthetic'
$env:DB_PASSWORD = 'synthetic'
$env:DB_NAME = 'synthetic'
$env:ENABLE_SCHEDULER = 'false'
$env:ENABLE_STARTUP_NAV_CHECK = 'false'
$env:NEWAPI_BASE_URL = 'http://127.0.0.1:1'
$env:NEWAPI_API_KEY = 'disabled'
$env:SMTP_HOST = '127.0.0.1'
$env:SMTP_PORT = '1'
$env:SMTP_USER = 'disabled'
$env:SMTP_PASSWORD = 'disabled'
$env:SMTP_TO = 'disabled@example.invalid'
# 合成测试：路由只读、当月预算、费用、旧报告、公开来源以及旧功能回归。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -B -m pytest backend/tests/test_purchase_delivery_preview.py backend/tests/test_public_purchase_source.py backend/tests/test_purchase_channel_policy.py backend/tests/test_advisor_execution_policy.py backend/tests/test_trade_execution_feedback_boundary.py backend/tests/test_advisor_email_boundary.py backend/tests/test_advisor_model_config.py backend/tests/test_advisor_operation_scope.py backend/tests/test_holding_ui_contract.py -q -p no:cacheprovider
# 真实Vue模板SSR和纯函数测试，不启动服务、不访问API。
& 'E:\NOdeJs1111111\node.exe' 'E:\myfund11111\fund-advisor\frontend\tests\purchase-channel-ui.test.mjs'
& 'E:\NOdeJs1111111\node.exe' 'E:\myfund11111\fund-advisor\frontend\tests\holding-import-ui.test.mjs'
```

最终结果：后端86 passed，退出码0；渠道前端9 passed、导入回归11 passed，退出码均0。不是全仓测试或生产验收。

离线Vite构建退出码0；产物仅写入全新临时目录：
`C:\Users\qwq\AppData\Local\Temp\mf-purchase-gate2-c8f7d42e7ca64de5b4009ad832422753`。

保留原有bundle超过500KB的性能提示；未处理其拆包，未以此扩大范围。SSR不等于浏览器视觉验收，未声称完成手机真机验收。

## 7. 保护对象与服务器证据

本阶段未编辑、更未暂存下列既有差异：

- `E:\myfund11111\fund-analyzer\tests\test_position.py`（SHA256仍为 `1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`）
- `E:\myfund11111\00_LUNA_START_HERE.md`
- `E:\myfund11111\LUNA_HANDOFF.md`
- `E:\myfund11111\docs\operations\CODEX_LUNA_ORCHESTRATION.md`
- `E:\myfund11111\docs\operations\OPENCLAW_CODEX_COLLABORATION.md`
- `E:\myfund11111\docs\operations\RUNBOOK.md`
- `E:\myfund11111\docs\operations\SYSTEM_ARCHITECTURE.md`
- `E:\myfund11111\docs\operations\CURRENT_CONTEXT.md`
- `E:\myfund11111\fund-advisor\CHANGELOG.md`
- `E:\myfund11111\ops\README.md`

服务器所有配置、镜像、服务、数据库、持仓、OpenClaw任务及邮件均在本阶段保护范围内；不修改邮件脚本、NewAPI、模型或凭据。

17:03起只读现场检查快照：生产前后端HTTP 200、容器running且restart=0；固定任务 `b230ae69-9887-476c-95f6-cc8051412037` 启用、空闲、上次ok、连续错误0，工作日14:00上海时间。不是21:04之后的新一轮现场核验。

实际任务通过独立OpenClaw发送脚本发送HTML，尚未引用新 `mail-preview`。生产没有新 `purchase_channel_service.py`。因此本地通过不能说明明天邮件已采用新版。

生产3个服务文件（execution_policy、mail_service、advisor_service）与本地HEAD字节哈希有差异，但完整AST摘要及逐函数AST均一致；只证明这3文件语法结构和常量基线一致，不等于生产全仓或字节一致。已消除此3文件基线疑点，不需重复全仓审查。

## 8. 已授权与仍需明确的动作

已执行：本地代码及合成测试、现有依赖离线构建、固定公开页面GET验证；本阶段此前严格SSH只读巡检，无远端写入。

尚未执行或取得本轮精确发布授权：Git暂存/提交/推送、服务器归档或镜像写入、应用部署、固定任务提示词接入新预览、实际报告生成或邮件测试。旧的其他SHA/文件集授权不自动套用。

尚缺的业务闭环是账户确认来源，而不是再修模型：只有公开信息，无法可靠得知用户是否开通天天基金、支付方式优惠及剩余额度；不得擅自登录、开户、预约或下单。本阶段没有把这个缺口伪装成已解决。

下一步仅围绕一个闭环推进：让用户在已有页面确认实际下单页信息并形成短时账户证据，再确定精确发布文件集和固定提交，接入原14:00任务的只读HTML预览。未经该闭环及明确发布授权，不整体上线强制渠道门禁，避免正向建议永久因缺账户证据而归零。

验收结论：两个只读入口及本地展示可以验收；生产升级、账户可买确认及新邮件链路尚未验收。禁止以“测试通过”宣称提高盈利已获证明。
