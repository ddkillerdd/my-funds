import test from 'node:test'
import assert from 'node:assert/strict'
import { quickRecordKey, retainPartialQuickRecords, validateHoldingFile, validateQuickRecord, labelHoldingValue, hasLoadingPreview, isValidLocalDate, localDateString } from '../src/utils/holdingImport.js'

test('快捷输入校验代码、金额、平台和本地日期', () => {
  assert.equal(validateQuickRecord({ fund_code: ' 000001 ', market_value: 10, platform: '平台A', share_date: '2026-09-05' }).ok, true)
  assert.equal(validateQuickRecord({ fund_code: '1', market_value: 10, platform: '平台A', share_date: '2026-09-05' }).ok, false)
  assert.equal(validateQuickRecord({ fund_code: '000001', market_value: Infinity, platform: '平台A', share_date: '2026-09-05' }).ok, false)
  assert.equal(validateQuickRecord({ fund_code: '000001', market_value: 10, platform: '', share_date: '2026-09-05' }).ok, false)
  assert.equal(isValidLocalDate('2026-99-99'), false)
  assert.equal(localDateString(new Date(2026, 8, 5)), '2026-09-05')
})

test('重复键允许同基金不同平台', () => {
  assert.notEqual(quickRecordKey({ fund_code: '000001', platform: 'A' }), quickRecordKey({ fund_code: '000001', platform: 'B' }))
})

test('任一行 loading 时批量操作保持禁用', () => {
  assert.equal(hasLoadingPreview([{ _status: 'ready' }, { _status: 'loading' }]), true)
  assert.equal(hasLoadingPreview([{ _status: 'ready' }]), false)
})

test('partial 只保留失败项并按代码平台匹配错误', () => {
  const records = [{ fund_code: '000001', platform: 'A' }, { fund_code: '000001', platform: 'B' }]
  const kept = retainPartialQuickRecords(records, { errors: [{ fund_code: '000001', platform: 'B', message: '净值失败' }] })
  assert.deepEqual(kept.map((item) => item.platform), ['B'])
  assert.equal(kept[0]._error, '净值失败')
})

test('预览失败项在其他记录成功时仍保留', () => {
  const records = [{ fund_code: '000001', platform: 'A', _status: 'error', _error: '预览净值不可用' }, { fund_code: '000002', platform: 'B', _status: 'ready' }]
  const kept = retainPartialQuickRecords(records, { errors: [] })
  assert.deepEqual(kept.map((item) => item.platform), ['A'])
  assert.equal(kept[0]._error, '预览净值不可用')
})

test('来源状态和变动类型中文映射', () => {
  assert.equal(labelHoldingValue('quick', 'source'), '快捷')
  assert.equal(labelHoldingValue('partial', 'status'), '部分成功')
  assert.equal(labelHoldingValue('clear', 'change'), '清仓')
})

test('文件只接受 xlsx zip 和 20 MiB', () => {
  assert.equal(validateHoldingFile({ name: 'a.xls', size: 1 }).ok, false)
  assert.equal(validateHoldingFile({ name: 'a.xlsx', size: 0 }).ok, false)
  assert.equal(validateHoldingFile({ name: 'a.xlsx', size: 20 * 1024 * 1024 + 1 }).ok, false)
  assert.equal(validateHoldingFile({ name: 'a.zip', size: 10 }).ok, true)
})
