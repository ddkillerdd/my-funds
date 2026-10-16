import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { createContext, Script } from 'node:vm'
import { computed, reactive, ref, watch } from 'vue'
import { parse, compileScript } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-ssr'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { formatRmb } from '../src/utils/purchaseChannel.js'
import { blankPurchaseConfirmation, buildPurchaseConfirmationPayload, confirmationFundOptions, confirmationReasonLabel, isConfirmationCurrent, paymentMethods, requestPurchaseConfirmation } from '../src/utils/purchaseConfirmation.js'

const observed = '2026-10-15T14:18:00+08:00'
const form = { fund_code: '013308', platform: '支付宝', payment_method: '银行卡', purchase_status: 'open', account_eligible: true,
  subscription_fee_rate_pct: '0.15', min_purchase_rmb: '1', verified_capacity_rmb: '20' }

// 读取真实组件脚本，只替换请求和生命周期，不复制业务函数实现。
async function harness(request) {
  const source = await readFile(new URL('../src/components/PurchaseConfirmation.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  compileScript(descriptor, { id: 'purchase-confirmation-test' })
  const lifecycle = []
  const context = createContext({ computed, reactive, ref, watch, Date, formatRmb, blankPurchaseConfirmation,
    buildPurchaseConfirmationPayload, confirmationFundOptions, confirmationReasonLabel, isConfirmationCurrent, paymentMethods,
    requestPurchaseConfirmation: request, onMounted: () => {}, onBeforeUnmount: callback => lifecycle.push(callback), clearInterval: () => {},
    defineProps: () => reactive({ reportId: 7, actions: [{ fund_code: '013308', fund_name: '合成基金' }] }),
  })
  new Script(descriptor.scriptSetup.content.replace(/^import .*$/gm, '') + '\nglobalThis.resultHarness = { form, props, acknowledged, observedAt, acknowledge, preview, result, busy, error, current }').runInContext(context)
  return { ...context.resultHarness, lifecycle }
}

test('初始无预填资格或费用，公共数据不能自动勾选账户确认', () => {
  const empty = blankPurchaseConfirmation()
  assert.equal(empty.account_eligible, false)
  assert.equal(empty.subscription_fee_rate_pct, null)
  assert.equal(empty.verified_capacity_rmb, null)
  assert.throws(() => buildPurchaseConfirmationPayload(form, false, observed))
  const options = confirmationFundOptions([{ fund_code: '013308' }, { fund_code: '013308' }, { fund_code: '999999' }])
  assert.equal(options.length, 1)
})

test('金额、时区、支付方式严格校验，未知不冒充零费率', () => {
  for (const patch of [{ subscription_fee_rate_pct: true }, { verified_capacity_rmb: '20.01' }, { verified_capacity_rmb: '0.001' },
    { subscription_fee_rate_pct: 'NaN' }, { min_purchase_rmb: -1 }, { platform: '天天基金', payment_method: '余额宝' }]) {
    assert.throws(() => buildPurchaseConfirmationPayload({ ...form, ...patch }, true, observed))
  }
  assert.throws(() => buildPurchaseConfirmationPayload(form, true, '2026-10-15T14:18:00'))
  const data = buildPurchaseConfirmationPayload({ ...form, subscription_fee_rate_pct: null, verified_capacity_rmb: '' }, true, observed)
  assert.equal(data.subscription_fee_rate_pct, null)
  assert.equal(data.verified_capacity_rmb, null)
  assert.equal(buildPurchaseConfirmationPayload({ ...form, subscription_fee_rate_pct: 0 }, true, observed).subscription_fee_rate_pct, '0')
})

test('当次请求仅POST只读预览，无保存、自动报告或发送端点', async () => {
  const calls = []
  const payload = buildPurchaseConfirmationPayload(form, true, observed)
  const response = { readonly: true, confirmation_saved: false, auto_order: false, delivery_actions: [] }
  assert.deepEqual(await requestPurchaseConfirmation(7, payload, async (...args) => { calls.push(args); return { ok: true, json: async () => response } }), response)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], '/api/advisor/report/7/purchase-preview')
  assert.equal(calls[0][1].method, 'POST')
  assert.deepEqual(JSON.parse(calls[0][1].body), payload)
  await assert.rejects(requestPurchaseConfirmation(7, payload, async () => ({ ok: false, status: 409 })), /新版当天报告/)
  await assert.rejects(requestPurchaseConfirmation(7, payload, async () => ({ ok: true, json: async () => ({ ...response, confirmation_saved: true }) })))
})

test('过期、未来或无有效期预览不能继续展示正向金额', () => {
  const data = { preview_at: '2026-10-15T14:20:00+08:00', valid_until: '2026-10-15T14:22:00+08:00' }
  assert.equal(isConfirmationCurrent(data, Date.parse('2026-10-15T14:21:00+08:00')), true)
  assert.equal(isConfirmationCurrent(data, Date.parse(data.valid_until)), false)
  assert.equal(isConfirmationCurrent(data, Date.parse('2026-10-15T14:19:00+08:00')), false)
  assert.equal(isConfirmationCurrent({}), false)
})

test('实际组件修改任一字段会清除勾选、时间和旧结果', async () => {
  const ui = await harness(async () => ({ readonly: true }))
  Object.assign(ui.form, form)
  ui.acknowledge(true)
  assert.ok(ui.observedAt.value)
  ui.form.subscription_fee_rate_pct = '0.12'
  assert.equal(ui.acknowledged.value, false)
  assert.equal(ui.observedAt.value, '')
  ui.acknowledge(true)
  ui.form.platform = '天天基金'
  assert.equal(ui.form.payment_method, '')
  assert.equal(ui.acknowledged.value, false)
})

test('实际组件重复试算不刷新证据时间，报告切换丢弃迟到结果', async () => {
  let resolve
  const pending = new Promise(done => { resolve = done })
  const ui = await harness(() => pending)
  Object.assign(ui.form, form)
  ui.acknowledge(true)
  const originalTime = ui.observedAt.value
  const running = ui.preview()
  assert.equal(ui.busy.value, true)
  ui.props.reportId = 8
  await Promise.resolve()
  resolve({ delivery_actions: [], preview_at: observed, valid_until: observed })
  await running
  assert.equal(ui.result.value, null)
  assert.equal(ui.busy.value, false)
  assert.equal(ui.observedAt.value, '')
  assert.ok(originalTime)
})

test('实际组件失败会清空旧结果并收口loading，离开页面忽略在途结果', async () => {
  const ui = await harness(async () => { throw new Error('合成读取失败') })
  Object.assign(ui.form, form)
  ui.acknowledge(true)
  await ui.preview()
  assert.equal(ui.busy.value, false)
  assert.equal(ui.result.value, null)
  assert.equal(ui.error.value, '合成读取失败')
  ui.lifecycle.forEach(callback => callback())
  let finish
  const other = await harness(() => new Promise(resolve => { finish = resolve }))
  Object.assign(other.form, form)
  other.acknowledge(true)
  const pending = other.preview()
  other.lifecycle.forEach(callback => callback())
  finish({ delivery_actions: [] })
  await pending
  assert.equal(other.result.value, null)
})

test('实际组件连续点击试算使用同一已确认时间，不伪造新证据', async () => {
  const times = []
  const ui = await harness(async (id, payload) => { times.push(payload.observed_at); return { delivery_actions: [] } })
  Object.assign(ui.form, form)
  ui.acknowledge(true)
  ui.observedAt.value = observed
  await ui.preview()
  await ui.preview()
  assert.deepEqual(times, [observed, observed])
})

test('真实模板转义名称且不渲染模型HTML或过期付款', async () => {
  const source = await readFile(new URL('../src/components/PurchaseConfirmation.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const compiled = compile(descriptor.template.content, { mode: 'function' })
  const ssrRender = new Function('require', compiled.code)(createRequire(import.meta.url))
  const html = await renderToString(createSSRApp({ ssrRender, setup: () => ({
    busy: false, form: blankPurchaseConfirmation(), funds: [], methods: [], acknowledged: false, error: '', current: false,
    result: { valid_until: observed, delivery_actions: [{ fund_name: '<img src=x>', fund_code: '013308', payment_rmb: 20, reasons: ['stale_report'] }] },
    formatRmb, confirmationReasonLabel,
  }) }))
  assert.ok(html.includes('不保存本次信息'))
  assert.ok(html.includes('0.00元'))
  assert.ok(!html.includes('总付款 20'))
  assert.ok(!html.includes('<img src=x>'))
  assert.ok(html.includes('&lt;img'))
  const page = await readFile(new URL('../src/views/AdvisorView.vue', import.meta.url), 'utf8')
  assert.ok(page.includes('<PurchaseConfirmation v-if="activeReportId" :key="activeReportId"'))
  assert.ok(!source.includes('v-html'))
})
