# 顾问分析可靠性修复与收益评估边界

任务：MF-ANALYSIS-RELIABILITY1-20261030-01。

结论：`PASS_LOCAL_ONLY`。本地已修改并合成验收，**没有提交、推送或生产部署**。

## 1. 现行证据与本次边界

修复前本地HEAD为`f89bc253b1b2be2b7054af802f12e15bb3121918`。本日只读核验显示生产仍是该次发布镜像，工作日14:00任务未变。

最近五个工作日中，10月27、28日是无新报告的technical_failure安全摘要；29、30日恢复生成报告。28日日志存在429线索，27日摘要存在500线索，但未取得能够独立证明所有历史失败根因的证据，不能宣称本次已彻底解决这两天的全部上游故障。

本次修复通过现行代码的合成失败夹具确定，不更换模型、关闭思考模式、扩大并发或放宽资金门禁。仅修改以下5个文件：

1. `E:\myfund11111\fund-analyzer\engine\llm_client.py`
2. `E:\myfund11111\fund-analyzer\tests\test_llm_reliability.py`（新建）
3. `E:\myfund11111\fund-advisor\backend\scheduler\advisor_job.py`
4. `E:\myfund11111\fund-advisor\backend\tests\test_advisor_job_reliability.py`（新建）
5. `E:\myfund11111\docs\operations\ANALYSIS_RELIABILITY_20261030.md`（本文件，新建）

## 2. 已实现的修复

### 模型传输、解析与重试

- JSON模式不再强制至少两次重试。`max_retries_per_model=0`只能请求一次，值为1时最多初次加一次重试；配置拒绝负数、布尔值和小数。
- 备用模型去重，显式model仍不自动更换模型。401/403停止本次逻辑调用，不通过反复请求或换模型试探同一无效凭据；其他不可重试4xx不在同一模型重复，仍可按配置尝试另一个模型。408、429、5xx保留原有有限重试，不宣称已新增完整Retry-After、自适应速率或全程墙钟截止。
- 标准JSON解码器处理包装文本中的字符串、转义引号和大括号，避免合法对象被手工数括号误判。无效代码块不能遮住后续合法对象；仍保留既有数组和双层字符串兼容，不据此放宽业务schema。
- JSON模式只认可正式content，不再把reasoning字段中的草稿当正式分析；非JSON兼容路径保持原行为。最终正文缺失应失败或走原降级，不伪造结论。
- 错误日志及最终异常不再包含模型响应片段、上游错误正文或提示词，仅保留错误类别、HTTP状态等诊断元数据。

### 顾问任务的诚实失败合同

- 分析抛异常或返回无效形态，返回`success=false`、`technical_failure=true`、`analysis=null`、`report_id=null`和阶段码；不让分析异常直接穿透成未处理500，不生成替代报告、不继续回测、不发邮件。
- 每次run清空旧report_id。要求保存报告但未取得新编号时，明确返回`report_persistence`阶段失败，不沿用旧报告、不宣称成功。
- 报告主记录提交并refresh后即记录新编号。后续非关键回测/清理失败时，保留已经真实存好的报告编号，避免“报告已存却向调用方报无编号”。
- API正常成功合同不变；失败响应新增结构化阶段。HTTP成功响应不代表业务成功，调用方须读取success、technical_failure和summary.report_id。

## 3. 验收证据

先写失败夹具，未改源码时运行：`17 failed, 2 passed`，退出码1。

关键失败包括：配置0次重试实际发3次；401/403配置主备后实际发6次；合法JSON字符串内括号导致解析失败；错误正文进入日志；reasoning被当正式JSON；重复模型重复调用；分析异常外溢；保存无新报告仍宣称成功或沿用旧编号。

第一轮源码修复后专项及旧模型/邮件/操作边界回归：`67 passed`。补充API失败合同、提交失败、提交后清理失败、重试配置和备用链夹具后，最终15个文件合成回归：

```text
211 passed, 1 warning in 2.81s
exit_code=0
```

唯一警告为旧SQLAlchemy默认`datetime.utcnow()`弃用警告，未扩大改ORM模型。`git diff --check`对两个修改源码通过；Git CRLF提示为既有换行策略，不是格式错误。本次不是全仓、真实模型、生产、邮件投递或盈利验收。

## 4. 可复验命令

环境：现有`E:\myfund11111\fund-advisor\.venv\Scripts\python.exe`，使用既有依赖，无安装或下载；HTTP传输为内存MockTransport，Session为虚构对象或原有内存SQLite夹具。禁用调度、启动回补，模型、数据库及SMTP指向不可用回环地址。

```powershell
# 仅做本地合成回归，不包含SSH、生产POST、模型调用或邮件发送。
Set-Location -LiteralPath 'E:\myfund11111\fund-advisor'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$env:DB_HOST='127.0.0.1'
$env:DB_PORT='1'
$env:DB_USER='synthetic'
$env:DB_PASSWORD='synthetic'
$env:DB_NAME='synthetic'
$env:ENABLE_SCHEDULER='false'
$env:ENABLE_STARTUP_NAV_CHECK='false'
$env:NEWAPI_BASE_URL='http://127.0.0.1:1/v1'
$env:NEWAPI_API_KEY='disabled'
$env:SMTP_HOST='127.0.0.1'
$env:SMTP_PORT='1'
$env:SMTP_USER='disabled'
$env:SMTP_PASSWORD='disabled'
$env:SMTP_TO='disabled@example.invalid'
$reliabilityTemp = Join-Path $env:TEMP ('mf-reliability-' + [guid]::NewGuid().ToString('N'))
$reliabilityTests = @(
  'E:\myfund11111\fund-analyzer\tests\test_llm_reliability.py',
  'E:\myfund11111\fund-analyzer\tests\test_llm_client.py',
  'E:\myfund11111\fund-analyzer\tests\test_decision.py',
  'E:\myfund11111\fund-analyzer\tests\test_quant.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_advisor_job_reliability.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_advisor_operation_scope.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_advisor_email_boundary.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_advisor_model_config.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_advisor_execution_policy.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_purchase_delivery_preview.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_purchase_confirmation.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_purchase_channel_policy.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_trade_execution_feedback_boundary.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_analysis_history_pnl.py',
  'E:\myfund11111\fund-advisor\backend\tests\test_holding_history_readers.py'
)
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -B -m pytest @reliabilityTests -q -p no:cacheprovider --basetemp $reliabilityTemp --tb=short
```

## 5. schema、保护及权限

- 无数据库schema、迁移、依赖、配置变量、资金/费用算法、前端、持仓或定时变化。
- 仅异常分支增加结构化失败响应，不改变正常成功响应合同或新增路由。
- `E:\myfund11111\fund-analyzer\tests\test_position.py`不在白名单，SHA256前后均为`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`。
- 既有入口、Luna交接、架构/运维文档、CHANGELOG、ops/README及CURRENT_CONTEXT差异保留，没有覆盖、清理或顺手暂存。
- 本次授权用于本地修复与合成验收；只读SSH仅补充历史证据和错误分类，没有生产写入。
- 尚未取得本次5文件的精确Git提交/推送和固定SHA生产后端切换授权，不复用旧任务的部署许可。现有生产继续运行旧镜像。

## 6. 关于“何时盈利”的评估

不能承诺日期。修复可靠性只能减少错误和无谓等待，不证明预测更准或必然赚钱。

当前49/64约76.6%为方向样本命中率，104条中性样本不在分母；不是扣费实盘收益。真实成交反馈为空，当前评估也不包含实际操作金额和费用，因此不能据此计算用户净收益或给盈利倒计时。

可验证的后续里程碑应分开：

1. **发布验收**：固定新提交、合成验收、仅后端切换、健康与运行源码哈希核对；不为验收生成报告或邮件。
2. **稳定性观察**：建议以上线后连续5个正常交易日为首轮观察窗，分别统计新报告是否生成、完成时间、降级、失败类别和单封投递；这是工程观察标准，不是自动监控授权或成功保证。
3. **效果初评**：新版真实建议至少经过现有20个自然日观察窗才开始具备到期反馈条件；还须真实成交/费用记录、最终可执行金额、统一观察终点与匹配基准。20天是当前验证机制，不是盈利期限或足够样本的保证。
4. **净收益证据**：扣除适用申购/赎回费用，对照相同现金流的持有基线，观察净收益、最大回撤、交易次数与样本覆盖。不能只选表现好的期间或用旧命中率替新版实盘证据。

深交所投教提醒，过往业绩不代表未来投资能力的承诺，短线择时困难且申赎成本会影响结果：
[基金投资风险防范技巧](https://investor.szse.cn/warning/t20210204_584672.html)。

本次没有通过改变策略参数或增加交易频率来制造看起来更积极的建议。

文件曾被修改：仅本节5项白名单；未Git写入、未部署、未改真实持仓或发送邮件。
