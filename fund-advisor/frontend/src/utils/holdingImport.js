/** 校验快捷导入输入并返回规范化值。 */
export function validateQuickRecord({ fund_code, market_value, platform, share_date }) {
  const code = String(fund_code ?? '').trim()
  const amount = Number(market_value)
  if (!/^\d{6}$/.test(code)) return { ok: false, message: '基金代码必须是 6 位数字' }
  if (!Number.isFinite(amount) || amount <= 0) return { ok: false, message: '持有金额必须是有限正数' }
  if (!String(platform ?? '').trim()) return { ok: false, message: '平台不能为空' }
  if (!isValidLocalDate(share_date)) return { ok: false, message: '请选择有效业务日期' }
  return { ok: true, value: { fund_code: code, market_value: amount, platform: String(platform).trim(), share_date } }
}

/** 使用本地年月日生成日期，避免 UTC 截断造成跨日。 */
export function localDateString(value = new Date()) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** 严格校验本地日历日期是否真实存在。 */
export function isValidLocalDate(value) {
  const text = String(value ?? '')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false
  const [year, month, day] = text.split('-').map(Number)
  const parsed = new Date(year, month - 1, day)
  return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === day
}

/** 返回基金代码与平台组成的稳定身份键。 */
export function quickRecordKey(record) {
  return `${String(record.fund_code ?? '').trim()}::${String(record.platform ?? '').trim()}`
}

/** 判断是否仍有任一行处于预览请求中。 */
export function hasLoadingPreview(records) {
  return records.some((record) => record._status === 'loading')
}

/** 部分成功时只移除成功身份，保留失败项及后端错误。 */
export function retainPartialQuickRecords(records, result) {
  const errors = Array.isArray(result?.errors) ? result.errors : []
  const failed = new Set(errors.map((item) => quickRecordKey(item)))
  return records.filter((record) => record._status === 'error' || failed.has(quickRecordKey(record)))
    .map((record) => ({ ...record, _error: errors.find((item) => quickRecordKey(item) === quickRecordKey(record))?.message ?? record._error ?? '导入失败' }))
}

/** 将来源、状态和变动类型转换为用户可读中文。 */
export function labelHoldingValue(value, kind) {
  const maps = {
    source: { manual: '手工', quick: '快捷', file: '文件', legacy: '历史' },
    status: { success: '成功', partial: '部分成功', duplicate: '重复', error: '失败' },
    change: { new: '新增', increase: '加仓', decrease: '减仓', clear: '清仓' },
  }
  return maps[kind]?.[value] ?? value
}

/** 校验文件扩展名与 20 MiB 大小限制。 */
export function validateHoldingFile(file) {
  const name = String(file?.name ?? '').toLowerCase()
  if (!/\.(xlsx|zip)$/.test(name)) return { ok: false, message: '仅支持 .xlsx 或 .zip 文件' }
  if (Number(file?.size ?? 0) <= 0) return { ok: false, message: '文件不能为空' }
  if (Number(file?.size ?? 0) > 20 * 1024 * 1024) return { ok: false, message: '文件不能超过 20 MiB' }
  return { ok: true }
}
