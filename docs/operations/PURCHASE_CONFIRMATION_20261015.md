# 下单页当次确认：第三轮本地交付与发布边界

任务：`MF-PURCHASE-CONFIRM1-20261015-01`。结论：`PASS_LOCAL_ONLY`。

## 1. 本轮完成了什么

在前两轮基础上补齐“查看报告 → 手动核对下单页 → 读取当前预算 → 含费试算 → 到期失效”的本地链路。

新增 `POST /api/advisor/report/{report_id}/purchase-preview`。POST仅为承载手动信息，不代表写数据库：仅SELECT既有报告、有效持仓代码和实际操作记录，不保存确认，不改报告，不更新持仓或现金，不生成报告、调用模型、发邮件、预约或交易。

现有应用路由未发现可复用的账户确认鉴权。本轮因此没有增加持久化额度写入口；请求者填写不等于已验证账户归属或平台API已验证，返回值明确标识这一区别。上线仍应核对现有应用访问保护，不以本接口取代登录鉴权。

## 2. 用户实际使用方式（上线后）

1. 在现有14:00报告中查看分析；不是每天必须买入。
2. 如果想核实某个买入候选，打开支付宝或天天基金的实际下单页，只查看，不点击付款、确认购买或预约。
3. 在顾问页面选择该基金、平台、支付方式，填写页面明确显示的实际申购费率、起购额和已核实本次至少可付款多少。20元是含费总付款上限，不是账户余额；未知留空。
4. 主动勾选核对声明，点击“确认并试算（不买入）”。服务器重查跨平台实际支出，最多输出日20元/月200元以内的含费付款。不能解除冷却期或数据质量拦截。
5. 试算不是额度预留，实际费用和成交份额以平台确认为准。若用户自己完成交易，仍走原实际操作反馈和持仓更新流程；本接口不自动记一笔买入，避免重复记录。

本次手动确认不进入后续定时任务。无人确认时日报仍可能安全显示0元，不能宣称自动掌握私有账户额度。邮件和页面不是自动交易系统，也不保证收益。

## 3. 输入、时效与正确性

- 范围仅为当前4只有效持仓代码；暂支持支付宝、天天基金。可在另一个平台核对同一代码，不会新增或覆盖任何平台的持仓。
- 初始费率、容量均未知，账户资格默认不勾选。公开页面、旧截图不会自动填成已确认；不接收账号、卡号、邮箱、密钥、任意来源URL或自动交易参数。
- 账户可买性使用严格布尔值；多余字段拒绝。费率和金额拒绝布尔值、NaN、Infinity、负值和越界值；金额最多到分。
- `verified_capacity_rmb`为用户当次核对的保守可付款下界，最大20元，不声称是账户完整额度；未知或不足起购额即0元。
- 仅允许重新评估原报告中“唯一原因是渠道未知”的同一基金候选。预算、冷却、单日单只、质量等原拦截不能通过确认解除。原始自由文字和目标仓位不能作为金额依据。
- 旧报告没有渠道门禁标记时返回409，不能凭新确认给旧报告补成可执行。当天报告和下单页证据仍须满足原30分钟规则。
- 展示有效期取以下最早时间：试算后5分钟、报告创建后30分钟、证据观察后30分钟、当天14:45。到期隐藏正向金额；重复点击试算不刷新证据观察时间。
- 编辑任何字段、切换报告或离开页面均使旧确认及旧结果失效；迟到响应不会覆盖新报告。
- 结果为0也须返回明确的预算、渠道或原门禁原因。暂停申购不自动预约，不自动换代码。

费用算例：总付款20元、申购费率0.15%，净投入 `20/(1+0.15/100)` 四舍五入到分为19.97元，费用0.03元。月内其他平台已付197元时最多再付3元；卖出不补月买入额度。费用只作预估，不以估算净值伪造实际份额。

## 4. 顺带修复的相关边界

内存SQLite复现：2026-06-01查询只从6月1日起读取，漏掉5月29日买入，连续工作日冷却错误关闭。修复为从“月初、上一个工作日”较早日期读取；月度金额仍只累计本月，不把上月支出计入本月。

这沿用既有周一至周五近似，不新增交易所日历；法定交易日仍由原OpenClaw门禁负责，不能声称已完成所有跨长假冷却建模。

原预览对归零动作可能返回空原因，本轮补齐固定中文原因；不显示自由模型指令。

## 5. 验收证据

先红后绿：

- 最小确认路由夹具修复前404，1 failed，退出码1；不是真实生产请求。
- 跨月冷却夹具修复前1 failed、36 passed；数据库仅为内存SQLite，未连接本机或服务器MySQL。
- 增加“归零必须解释”断言后17 failed、20 passed，修复原因保留和渲染后通过。

最终后端10文件合成回归：123 passed，退出码0；前端确认9 passed、渠道9 passed、持仓导入11 passed，共29项，退出码均0。

保留ORM旧UTC默认方法的一条弃用警告，不扩大修改模型。不是全仓测试、MySQL集成测试、生产验收或手机视觉验收。

离线前端构建成功，退出码0，产物仅在新临时目录：
`C:\Users\qwq\AppData\Local\Temp\mf-purchase-confirmation-125bdfd4304e4dffaf240a7312d3d2f3`。
既有大bundle警告保留；未安装或下载依赖，未覆盖仓库dist。

测试环境及可复制命令：

```powershell
# 仅运行合成测试；所有外部服务指向不可用的本地地址。
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
# 其中跨月夹具仅创建内存SQLite并写虚构记录，退出后不持久化。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -B -m pytest backend/tests/test_purchase_confirmation.py backend/tests/test_purchase_delivery_preview.py backend/tests/test_public_purchase_source.py backend/tests/test_purchase_channel_policy.py backend/tests/test_advisor_execution_policy.py backend/tests/test_trade_execution_feedback_boundary.py backend/tests/test_advisor_email_boundary.py backend/tests/test_advisor_model_config.py backend/tests/test_advisor_operation_scope.py backend/tests/test_holding_ui_contract.py -q -p no:cacheprovider
# 真实组件脚本、SSR和纯函数测试，不启动应用、不访问API。
& 'E:\NOdeJs1111111\node.exe' 'E:\myfund11111\fund-advisor\frontend\tests\purchase-confirmation-ui.test.mjs'
& 'E:\NOdeJs1111111\node.exe' 'E:\myfund11111\fund-advisor\frontend\tests\purchase-channel-ui.test.mjs'
& 'E:\NOdeJs1111111\node.exe' 'E:\myfund11111\fund-advisor\frontend\tests\holding-import-ui.test.mjs'
```

Python 3.12.13；Node 24.15.0；使用现有依赖。命令不含SSH、生产API、邮件发送或模型推理。

## 6. 本轮白名单、保护及schema

本轮11项精确范围为第7节中的3、4、5、7、9、10、15、16、19、21、23项；这些文件可以修改，不同时列为保护对象。

保护并保留所有其余既有差异，尤其：
`E:\myfund11111\fund-analyzer\tests\test_position.py`，SHA256仍为
`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`。

前轮重要说明 `E:\myfund11111\docs\operations\PURCHASE_CHANNEL_DELIVERY_20261015.md` 未覆盖，SHA256仍为 `E16B8BD99CA8989D928DCD2C57E27E7DA2C3D02CED3F6D6C3B5FCEB51059BE16`。旧入口/交接/架构/运维文档差异不在本次修改或提交范围；未清理旧权限异常目录。

无数据库schema、迁移、依赖、环境变量、任务定时或模型配置变化。新增的是请求校验schema，不是数据库schema。确认值仅在内存，不写AppConfig、报告或持仓表；没有新增长期账户额度来源。

本轮未进行SSH、服务器操作、真实数据读取、报告生成、模型调用或邮件操作。HEAD仍为 `ccab61e01407e2b28409b2a56efef010ee81073f`，未Git写入。

## 7. 累计23项发布候选清单（不是已授权执行）

1. `E:\myfund11111\docs\operations\PURCHASE_CHANNEL_GATE_20261015.md`
2. `E:\myfund11111\docs\operations\PURCHASE_CHANNEL_DELIVERY_20261015.md`
3. `E:\myfund11111\docs\operations\PURCHASE_CONFIRMATION_20261015.md`
4. `E:\myfund11111\fund-advisor\backend\api\advisor.py`
5. `E:\myfund11111\fund-advisor\backend\services\execution_policy.py`
6. `E:\myfund11111\fund-advisor\backend\services\purchase_channel_service.py`
7. `E:\myfund11111\fund-advisor\backend\services\decision_delivery_service.py`
8. `E:\myfund11111\fund-advisor\backend\services\public_purchase_source.py`
9. `E:\myfund11111\fund-advisor\backend\services\purchase_confirmation_service.py`
10. `E:\myfund11111\fund-advisor\backend\schemas\purchase_confirmation.py`
11. `E:\myfund11111\fund-advisor\backend\tests\test_advisor_execution_policy.py`
12. `E:\myfund11111\fund-advisor\backend\tests\test_purchase_channel_policy.py`
13. `E:\myfund11111\fund-advisor\backend\tests\test_purchase_delivery_preview.py`
14. `E:\myfund11111\fund-advisor\backend\tests\test_public_purchase_source.py`
15. `E:\myfund11111\fund-advisor\backend\tests\test_purchase_confirmation.py`
16. `E:\myfund11111\fund-advisor\frontend\src\views\AdvisorView.vue`
17. `E:\myfund11111\fund-advisor\frontend\src\components\PurchaseCheck.vue`
18. `E:\myfund11111\fund-advisor\frontend\src\components\PublicPurchaseOptions.vue`
19. `E:\myfund11111\fund-advisor\frontend\src\components\PurchaseConfirmation.vue`
20. `E:\myfund11111\fund-advisor\frontend\src\utils\purchaseChannel.js`
21. `E:\myfund11111\fund-advisor\frontend\src\utils\purchaseConfirmation.js`
22. `E:\myfund11111\fund-advisor\frontend\tests\purchase-channel-ui.test.mjs`
23. `E:\myfund11111\fund-advisor\frontend\tests\purchase-confirmation-ui.test.mjs`

## 8. 下一步：一次明确发布授权，不再增加功能模块

已完成的授权范围：本地开发、合成验收、现有依赖离线构建和文档。本轮没有取得针对这23项的Git写入、服务器应用切换或固定任务改写授权，不能套用过去其他SHA的授权。

如用户希望正式上线，可单独批准下述具体范围；此段本身不构成授权：

> 授权 MF-PURCHASE-RELEASE1：允许Codex仅对第7节23个文件精确暂存、在codex分支创建一个本地提交并推送（禁止强推）；再通过现有严格SCP/SSH，先只读核对生产基线、现有应用访问边界及固定任务空闲状态，保存0600更新前配置快照，以该固定提交和现有镜像离线派生新backend/frontend，只替换并重建这两个应用服务。允许只读健康、页面及合成预览验收；成功后仅调整固定任务b230ae69-9887-476c-95f6-cc8051412037的邮件渲染步骤，使用mail-preview最终动作与原因，保留已有市场和持仓展示、任务ID、工作日14:00、模型、预算、收件人和每日一封规则。不立即运行任务、生成报告或发送邮件。失败时允许恢复原Compose、镜像及该任务原渲染步骤。禁止数据库迁移或生产数据写入、持仓、NewAPI、其他任务、收件人变更、外网下载及自动重试。若访问边界或生产差异不能确认则停止，不擅自修改认证或网络设置。

发布前必须记录实际创建的完整提交SHA、归档及镜像校验值；不能用工作区或本地构建成功代替生产验收。发布后验收不允许为了测试而真实买入、保存用户确认、生成报告或发测试邮件。
