import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createContext, Script } from 'node:vm'
import { computed, effect, ref } from '@vue/reactivity'
import { quickRecordKey, retainPartialQuickRecords, validateHoldingFile, validateQuickRecord, labelHoldingValue, hasLoadingPreview, isValidLocalDate, localDateString, QUICK_PREVIEW_TIMEOUT_MS, isPreviewCanceled, previewErrorMessage } from '../src/utils/holdingImport.js'

// 创建可控的异步结果，供真实组件脚本 harness 模拟首次预览和竞态响应。
function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

// 读取并执行实际 ImportView.vue 脚本，只替换外部 API 和生命周期依赖。
async function loadImportViewHarness(previewImpl, { legacyRawRow = false } = {}) {
  const file = new URL('../src/views/ImportView.vue', import.meta.url)
  const source = await readFile(file, 'utf8')
  const match = source.match(/<script setup>\s*([\s\S]*?)\s*<\/script>/)
  assert.ok(match, 'ImportView.vue 必须包含 script setup')
  let scriptSource = match[1].replace(/^import .*$/gm, '')
  if (legacyRawRow) {
    const currentCall = 'await previewQuickRecord(quickRecords.value[quickRecords.value.length - 1])'
    assert.equal(scriptSource.includes(currentCall), true)
    scriptSource = scriptSource.replace(currentCall, 'await previewQuickRecord(row)')
  }
  const lifecycle = []
  const context = createContext({
    AbortController,
    computed,
    effect,
    ref,
    onMounted: () => {},
    onBeforeUnmount: (callback) => lifecycle.push(callback),
    ElMessage: { warning: () => {}, error: () => {}, success: () => {} },
    uploadExcel: async () => ({}),
    getImportHistory: async () => [],
    getImportChanges: async () => [],
    simpleImport: async () => ({ success: 0, errors: [] }),
    previewSimpleImport: (...args) => previewImpl(...args),
    getOperationHistory: async () => [],
    validateQuickRecord,
    quickRecordKey,
    retainPartialQuickRecords,
    labelHoldingValue,
    validateHoldingFile,
    hasLoadingPreviewRows: hasLoadingPreview,
    localDateString,
    isPreviewCanceled,
    previewErrorMessage,
  })
  new Script(`${scriptSource}\nglobalThis.__harness = { quickFundCode, quickAmount, quickRecords, quickPlatform, quickShareDate, addQuickRecord, retryQuickRecord, removeQuickRecord, clearQuickRecords }`).runInContext(context)
  return { ...context.__harness, lifecycle }
}

// 设置快捷导入输入并等待真实组件脚本创建预览请求。
function setQuickInput(harness) {
  harness.quickFundCode.value = '000001'
  harness.quickAmount.value = '100'
  harness.quickPlatform.value = '支付宝'
  harness.quickShareDate.value = '2026-09-06'
}

// 等待组件脚本中的 Promise 微任务完成。
async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

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
  const row = { fund_code: '000001', platform: 'A' }
  assert.equal(quickRecordKey(row), quickRecordKey(new Proxy({ ...row }, {})))
})

test('快捷预览取消静默且超时收口为中文', () => {
  const controller = new AbortController()
  controller.abort()
  assert.equal(QUICK_PREVIEW_TIMEOUT_MS, 15000)
  assert.equal(isPreviewCanceled({ code: 'ERR_CANCELED' }, controller.signal), true)
  assert.equal(isPreviewCanceled({ name: 'CanceledError' }, new AbortController().signal), true)
  assert.equal(isPreviewCanceled({ code: 'ECONNABORTED' }, new AbortController().signal), false)
  assert.equal(previewErrorMessage({ code: 'ECONNABORTED', message: 'timeout of 15000ms exceeded' }), '基金信息获取超时，请重新获取')
  assert.equal(previewErrorMessage({ code: 'ETIMEDOUT', message: 'request timed out' }), '基金信息获取超时，请重新获取')
})

test('首次快捷预览写入 ref 数组中的 proxy 行后 loading 能收口', () => {
  const records = ref([])
  const observed = []
  effect(() => observed.push(records.value[0]?._status ?? 'empty'))
  const rawRow = { _status: 'loading', _error: '' }
  records.value.push(rawRow)
  const proxyRow = records.value[0]
  assert.notEqual(proxyRow, rawRow)

  proxyRow._status = 'ready'
  assert.equal(records.value[0]._status, 'ready')
  proxyRow._status = 'loading'
  proxyRow._error = '基金信息获取超时，请重新获取'
  proxyRow._status = 'error'
  assert.equal(records.value[0]._status, 'error')
  assert.deepEqual(observed, ['empty', 'loading', 'ready', 'loading', 'error'])
})

test('实际 ImportView 首次成功和超时路径收口 loading，旧 raw 版本会失败', async () => {
  const preview = { fund_name: '测试基金', estimated_shares: 10, latest_nav: 1.2, latest_nav_date: '2026-09-05' }
  const current = await loadImportViewHarness(() => Promise.resolve(preview))
  const currentStatuses = []
  effect(() => currentStatuses.push(current.quickRecords.value[0]?._status ?? 'empty'))
  setQuickInput(current)
  await current.addQuickRecord()
  assert.equal(current.quickRecords.value[0]._status, 'ready')
  assert.equal(currentStatuses.at(-1), 'ready')

  const currentTimeout = await loadImportViewHarness(() => Promise.reject({ code: 'ECONNABORTED', message: 'timeout' }))
  const timeoutStatuses = []
  effect(() => timeoutStatuses.push(currentTimeout.quickRecords.value[0]?._status ?? 'empty'))
  setQuickInput(currentTimeout)
  await currentTimeout.addQuickRecord()
  assert.equal(currentTimeout.quickRecords.value[0]._status, 'error')
  assert.equal(timeoutStatuses.at(-1), 'error')
  assert.equal(currentTimeout.quickRecords.value[0]._error, '基金信息获取超时，请重新获取')

  const legacy = await loadImportViewHarness(() => Promise.resolve(preview), { legacyRawRow: true })
  const legacyStatuses = []
  effect(() => legacyStatuses.push(legacy.quickRecords.value[0]?._status ?? 'empty'))
  setQuickInput(legacy)
  await legacy.addQuickRecord()
  assert.equal(legacy.quickRecords.value[0]._status, 'ready')
  assert.equal(legacyStatuses.at(-1), 'loading')

  const legacyTimeout = await loadImportViewHarness(() => Promise.reject({ code: 'ECONNABORTED', message: 'timeout' }), { legacyRawRow: true })
  const legacyTimeoutStatuses = []
  effect(() => legacyTimeoutStatuses.push(legacyTimeout.quickRecords.value[0]?._status ?? 'empty'))
  setQuickInput(legacyTimeout)
  await legacyTimeout.addQuickRecord()
  assert.equal(legacyTimeout.quickRecords.value[0]._status, 'error')
  assert.equal(legacyTimeoutStatuses.at(-1), 'loading')
})

test('实际 ImportView 删除、清空和重试竞态保持取消边界', async () => {
  const requests = []
  const harness = await loadImportViewHarness(() => {
    const request = deferred()
    requests.push(request)
    return request.promise
  })
  setQuickInput(harness)
  const firstAdd = harness.addQuickRecord()
  await flushPromises()
  harness.removeQuickRecord(harness.quickRecords.value[0], 0)
  assert.equal(harness.quickRecords.value.length, 0)
  requests[0].resolve({ fund_name: '删除后不应回写' })
  await firstAdd
  assert.equal(harness.quickRecords.value.length, 0)

  setQuickInput(harness)
  harness.quickFundCode.value = '000002'
  const secondAdd = harness.addQuickRecord()
  await flushPromises()
  setQuickInput(harness)
  harness.quickFundCode.value = '000003'
  const thirdAdd = harness.addQuickRecord()
  await flushPromises()
  assert.equal(harness.quickRecords.value.length, 2)
  harness.clearQuickRecords()
  assert.equal(harness.quickRecords.value.length, 0)
  requests[1].resolve({ fund_name: '清空后不应回写' })
  requests[2].resolve({ fund_name: '清空后不应回写' })
  await Promise.all([secondAdd, thirdAdd])
  assert.equal(harness.quickRecords.value.length, 0)

  const retryRequests = []
  const retryHarness = await loadImportViewHarness(() => {
    const request = deferred()
    retryRequests.push(request)
    return request.promise
  })
  setQuickInput(retryHarness)
  const originalAdd = retryHarness.addQuickRecord()
  await flushPromises()
  const retryRow = retryHarness.quickRecords.value[0]
  retryHarness.retryQuickRecord(retryRow)
  await flushPromises()
  assert.equal(retryRequests.length, 2)
  retryRequests[0].resolve({ fund_name: '旧请求' })
  await flushPromises()
  assert.equal(retryHarness.quickRecords.value[0]._status, 'loading')
  retryRequests[1].resolve({ fund_name: '新请求', estimated_shares: 1, latest_nav: 1, latest_nav_date: '2026-09-06' })
  await Promise.all([originalAdd, flushPromises()])
  assert.equal(retryHarness.quickRecords.value[0]._status, 'ready')
  assert.equal(retryHarness.quickRecords.value[0]._resolved_name, '新请求')
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
