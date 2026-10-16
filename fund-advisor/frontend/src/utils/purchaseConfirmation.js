// 明确支持的平台及支付类型，不接收银行卡号或任意账户文本。
export const paymentMethods = { '支付宝': ['银行卡', '支付宝余额', '余额宝'], '天天基金': ['银行卡', '活期宝'] }
const currentCodes = new Set(['013308', '022430', '270042', '018044'])

// 所有下单页字段初始未知，不从旧截图或公开来源自动勾选账户确认。
export function blankPurchaseConfirmation() {
  return { fund_code: '', platform: '', payment_method: '', purchase_status: 'unknown', account_eligible: false,
    subscription_fee_rate_pct: null, min_purchase_rmb: null, verified_capacity_rmb: null }
}

// 只列出本报告中当前四只基金，不由输入动作创建新的持仓。
export function confirmationFundOptions(actions) {
  const seen = new Set()
  return (Array.isArray(actions) ? actions : []).filter(item => {
    if (!item || !currentCodes.has(item.fund_code) || seen.has(item.fund_code)) return false
    seen.add(item.fund_code)
    return true
  })
}

// 把用户主动确认转换成限字段请求；空值仍为未知，零费率必须明确输入。
export function buildPurchaseConfirmationPayload(form, confirmed, observedAt) {
  if (confirmed !== true || !currentCodes.has(form.fund_code)) throw new Error('请先选择当前持仓并主动核对确认')
  if (!paymentMethods[form.platform]?.includes(form.payment_method)) throw new Error('请选择平台和对应支付方式，不填写账号')
  if (!['open', 'paused', 'unknown'].includes(form.purchase_status) || typeof form.account_eligible !== 'boolean') throw new Error('可买状态格式异常')
  if (typeof observedAt !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/.test(observedAt) || !Number.isFinite(Date.parse(observedAt))) throw new Error('确认时间无效，请重新核对')
  const payload = { fund_code: form.fund_code, platform: form.platform, payment_method: form.payment_method,
    purchase_status: form.purchase_status, account_eligible: form.account_eligible, observed_at: observedAt, confirmed_by_user: true }
  for (const key of ['subscription_fee_rate_pct', 'min_purchase_rmb', 'verified_capacity_rmb']) {
    const raw = form[key]
    if (raw === null || raw === undefined || raw === '') { payload[key] = null; continue }
    if (typeof raw === 'boolean' || !/^(?:\d+)(?:\.\d+)?$/.test(String(raw))) throw new Error('金额或费率必须是非负有限数，未知请留空')
    const value = Number(raw)
    const cap = key === 'subscription_fee_rate_pct' ? 100 : key === 'verified_capacity_rmb' ? 20 : 1e12
    if (!Number.isFinite(value) || value < 0 || value > cap || (key === 'min_purchase_rmb' && value < 0.01)) throw new Error('费率或可付款上限超出范围')
    if (key !== 'subscription_fee_rate_pct' && Math.abs(value * 100 - Math.round(value * 100)) > 1e-6) throw new Error('金额最多填写到分')
    payload[key] = String(raw)
  }
  return payload
}

// POST仅承载当次核对字段；后端只读试算，无保存、报告生成或邮件副作用。
export async function requestPurchaseConfirmation(reportId, payload, request = fetch) {
  if (!Number.isSafeInteger(reportId) || reportId <= 0) throw new Error('请先选择已保存的报告')
  const response = await request(`/api/advisor/report/${reportId}/purchase-preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(10000),
  })
  if (!response.ok) {
    const messages = { 409: '该报告不支持确认，请使用新版当天报告', 422: '填写信息不完整或不在当前持仓范围，请重新核对', 404: '报告不存在，请重新选择' }
    throw new Error(messages[response.status] || '只读复核未完成，不操作；未保存或下单')
  }
  const data = await response.json()
  if (data.readonly !== true || data.confirmation_saved !== false || data.auto_order !== false || !Array.isArray(data.delivery_actions)) throw new Error('试算结果格式异常，请勿操作')
  return data
}

// 页面停留时主动隐藏到期正向金额，不把一次试算永久当作可买证明。
export function isConfirmationCurrent(result, now = Date.now()) {
  if (!result || typeof result.valid_until !== 'string' || typeof result.preview_at !== 'string') return false
  const start = Date.parse(result.preview_at)
  const end = Date.parse(result.valid_until)
  return Number.isFinite(start) && Number.isFinite(end) && now >= start && now < end
}

// 仅展示固定安全原因，不将模型自由文字或原始金额恢复成指令。
export function confirmationReasonLabel(reason) {
  const labels = {
    stale_report: '报告过期或时间异常', outside_decision_window: '不在工作日14:00至14:45决策窗口',
    analysis_not_ready: '分析降级或数据质量不足', budget_not_rechecked: '预算未能复核',
    policy_blocked: '原预算、冷却或质量门禁未通过', channel_unverified: '账户可买性、费率或额度仍未核实',
    multiple_buy_candidates: '多条买入候选不符合单日单只规则', redemption_fee_unverified: '赎回费用和批次未核验',
    invalid_action: '动作或金额异常', legacy_report: '旧报告不作为操作依据',
    daily_buy_limit_reached: '今日20元付款额度已用完', monthly_buy_limit_reached: '本月200元付款额度已用完',
    consecutive_trading_day_cooldown: '连续操作冷却尚未解除', single_fund_daily_limit: '单日只买一只的限制未解除',
    analysis_degraded: '原分析已降级', purchase_channel_unverified: '账户可买性、费率或容量仍未核实',
  }
  return labels[reason] || '本次没有可执行资金操作'
}
