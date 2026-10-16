// 只认可同一上海日期、非未来且30分钟内的渠道快照；旧报告不能当作当前买入指令。
export function isCurrentPurchaseCheck(check, now = new Date()) {
  if (check?.status !== 'checked' || typeof check.observed_at !== 'string') return false
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(check.observed_at)) return false
  const observed = new Date(check.observed_at)
  const clock = now instanceof Date ? now : new Date(now)
  const age = clock.getTime() - observed.getTime()
  if (!Number.isFinite(age) || age < 0 || age > 30 * 60 * 1000) return false
  const shanghaiDay = (date) => new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 10)
  return shanghaiDay(observed) === shanghaiDay(clock)
}

// 兼容旧报告的正向候选，缺少渠道核验时也必须显示待确认提示。
export function isBuyCandidate(action) {
  return ['buy', 'add', 'increase'].includes(action.action)
    || Number(action.action_amount) > 0
    || Number(action.raw_action_amount) > 0
}

// 金额及手续费保留到分，不把小额持仓或费用显示成零。
export function formatRmb(value) {
  return value == null || !Number.isFinite(Number(value))
    ? '未核验'
    : `${Number(value).toFixed(2)} 元`
}

// 将渠道拦截原因转成人话，避免暂停申购与未知费率混成一句模糊错误。
export function channelReasonLabel(reason) {
  const labels = {
    purchase_not_open: '暂停申购或状态未知',
    account_not_confirmed: '尚未确认你的账户能交易',
    quote_source_missing: '缺少代码、平台、支付方式或证据来源',
    unsupported_fee_mode: '特殊收费方式尚不支持试算',
    fee_or_limit_unknown: '费率、起购额或剩余额度未知',
    quote_expired_or_future: '快照过期或时间异常',
    quote_time_invalid: '核验时间缺失或没有时区',
    duplicate_channel_quote: '同一渠道有重复证据，需先消歧',
    below_channel_minimum_or_no_quota: '可用金额不足起购额，或渠道额度已用完',
  }
  return labels[reason] || reason
}

// 公开状态只作渠道线索，绝不转换为账户可买或预约指令。
export function publicStatusLabel(status) {
  return { open: '公开页面显示开放', limited: '公开页面显示限额', paused: '暂停申购' }[status] || '未知'
}

// 未知费率不能显示成零，异常及布尔字段也不能当作数字。
export function publicFeeLabel(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? `${value}%` : '未知'
}

// 来源链接只由允许的基金代码构造，不能把上游文本变成任意链接。
export function publicSourceUrl(code) {
  return ['013308', '022430', '270042', '018044'].includes(code)
    ? `https://fundf10.eastmoney.com/jjfl_${code}.html` : undefined
}

// 手动请求只读公开入口，无自动刷新、重试或任何账户写入。
export async function queryPublicPurchaseOptions(request = fetch) {
  const response = await request('/api/advisor/purchase-options/public', {
    method: 'GET', signal: AbortSignal.timeout(25000),
  })
  if (!response.ok) throw new Error('公开来源暂不可用')
  const data = await response.json()
  if (data.readonly !== true || data.account_verified !== false || !Array.isArray(data.items)) throw new Error('公开来源返回格式异常')
  return data.items.filter(item => item && publicSourceUrl(item.fund_code) && item.evidence_scope === 'public_only')
}
