import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { parse, compileScript } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-ssr'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { channelReasonLabel, isBuyCandidate, isCurrentPurchaseCheck, formatRmb } from '../src/utils/purchaseChannel.js'
import { publicStatusLabel, publicFeeLabel, publicSourceUrl, queryPublicPurchaseOptions } from '../src/utils/purchaseChannel.js'

const now = Date.parse('2026-10-15T14:00:00+08:00')
const checked = {
  status: 'checked', observed_at: '2026-10-15T13:55:00+08:00',
  platform: '合成平台', payment_method: '合成支付', source: '合成夹具',
  gross_payment_rmb: 20, subscription_fee_rate_pct: 0.15,
  estimated_fee_rmb: 0.03, estimated_net_investment_rmb: 19.97,
}

// 编译并服务端渲染真实组件模板，完全不启动应用、不访问API。
async function renderCheck(check) {
  const source = await readFile(new URL('../src/components/PurchaseCheck.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  compileScript(descriptor, { id: 'purchase-test' })
  const compiled = compile(descriptor.template.content, { mode: 'function' })
  const ssrRender = new Function('require', compiled.code)(createRequire(import.meta.url))
  const app = createSSRApp({
    ssrRender,
    setup: () => ({ check, now, channelReasonLabel, formatRmb, isCurrentPurchaseCheck }),
  })
  return renderToString(app)
}

test('旧报告、公共状态、过期与未来快照不能展示为当前通过', () => {
  assert.equal(isCurrentPurchaseCheck(null, now), false)
  assert.equal(isCurrentPurchaseCheck({ ...checked, status: 'blocked' }, now), false)
  assert.equal(isCurrentPurchaseCheck(checked, now), true)
  assert.equal(isCurrentPurchaseCheck(checked, now + 30 * 60 * 1000), false)
  assert.equal(isCurrentPurchaseCheck({ ...checked, observed_at: '2026-10-15T14:01:00+08:00' }, now), false)
  assert.equal(isCurrentPurchaseCheck({ ...checked, observed_at: '2026-10-15T13:55:00' }, now), false)
  assert.equal(isCurrentPurchaseCheck({ ...checked, observed_at: '2026-10-15T05:55:00Z' }, now), true)
})

test('跨上海日期的快照即使只相差几分钟也失效', () => {
  assert.equal(isCurrentPurchaseCheck({ ...checked, observed_at: '2026-10-15T23:59:00+08:00' }, Date.parse('2026-10-16T00:01:00+08:00')), false)
})

test('手续费显示到分，正向旧建议与归零候选均识别', () => {
  assert.equal(formatRmb(0.03), '0.03 元')
  assert.equal(formatRmb(null), '未核验')
  assert.equal(isBuyCandidate({ action: 'buy', action_amount: 0 }), true)
  assert.equal(isBuyCandidate({ action: 'hold', raw_action_amount: 20, action_amount: 0 }), true)
  assert.equal(isBuyCandidate({ action: 'reduce', action_amount: -10 }), false)
})

test('真实组件呈现含费付款、净投入与人工交易边界', async () => {
  const html = await renderCheck(checked)
  for (const text of ['合成平台', '20.00 元', '0.03 元', '19.97 元', '不预约', '不下单', '不代表持有期总成本最低']) assert.ok(html.includes(text), text)
})

test('真实组件缺失核验时不泄漏旧正向付款，来源文本会转义', async () => {
  const blocked = await renderCheck(null)
  assert.ok(blocked.includes('暂不执行买入'))
  assert.ok(!blocked.includes('总付款 20'))
  const escaped = await renderCheck({ ...checked, source: '<img src=x onerror=alert(1)>' })
  assert.ok(!escaped.includes('<img src=x'))
  assert.ok(escaped.includes('&lt;img'))
})

test('真实组件明确显示暂停申购和额度不足的不同原因', async () => {
  const html = await renderCheck({ status: 'blocked', channels: [
    { platform: '合成平台甲', reasons: ['purchase_not_open'] },
    { platform: '合成平台乙', reasons: ['below_channel_minimum_or_no_quota'] },
  ] })
  assert.ok(html.includes('暂停申购或状态未知'))
  assert.ok(html.includes('可用金额不足起购额'))
})

test('顾问页面确实接入渠道组件和时效检查且没有新增下单或预约入口', async () => {
  const page = await readFile(new URL('../src/views/AdvisorView.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(page)
  compileScript(descriptor, { id: 'advisor-purchase-test' })
  assert.ok(page.includes('<PurchaseCheck v-if="isBuyCandidate(a)"'))
  assert.ok(page.includes('isCurrentPurchaseCheck(a.purchase_check, purchaseClock)'))
  assert.ok(page.includes('clearInterval(purchaseClockTimer)'))
  assert.ok(page.includes('方向命中率不是赚钱概率'))
  assert.ok(!page.includes('maximumFractionDigits: 0'))
})

test('公开查询只调用只读GET且不信任错误账户标记或任意来源', async () => {
  const calls = []
  const result = await queryPublicPurchaseOptions(async (...args) => {
    calls.push(args)
    return { ok: true, json: async () => ({ readonly: true, account_verified: false, items: [
      { fund_code: '013308', evidence_scope: 'public_only' },
      { fund_code: '999999', evidence_scope: 'public_only' },
      { fund_code: '018044', evidence_scope: 'account_confirmed' },
    ] }) }
  })
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], '/api/advisor/purchase-options/public')
  assert.equal(calls[0][1].method, 'GET')
  assert.equal(result.length, 1)
  await assert.rejects(queryPublicPurchaseOptions(async () => ({ ok: true, json: async () => ({ readonly: true, account_verified: true, items: [] }) })))
  assert.equal(publicSourceUrl('javascript:alert(1)'), undefined)
  assert.equal(publicFeeLabel(null), '未知')
  assert.equal(publicFeeLabel(true), '未知')
  assert.equal(publicFeeLabel(0), '0%')
  assert.equal(publicStatusLabel('paused'), '暂停申购')
})

test('真实公开组件显示未知而非免费，来源转义且没有买入按钮', async () => {
  const source = await readFile(new URL('../src/components/PublicPurchaseOptions.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  compileScript(descriptor, { id: 'public-purchase-test' })
  // 本测试检查业务模板和转义，不把Element Plus组件库当成缺失业务组件。
  const compiled = compile(descriptor.template.content, { mode: 'function', isCustomElement: tag => tag.startsWith('el-') })
  const ssrRender = new Function('require', compiled.code)(createRequire(import.meta.url))
  const app = createSSRApp({ ssrRender, setup: () => ({
    loading: false, error: '', items: [{ fund_code: '013308', purchase_status: 'paused', subscription_fee_rate_pct: null, min_purchase_rmb: null, observed_at: '<img src=x>' }],
    formatRmb, publicSourceUrl, statusLabel: publicStatusLabel, feeLabel: publicFeeLabel,
  }) })
  const html = await renderToString(app)
  assert.ok(html.includes('暂停申购'))
  assert.ok(html.includes('未知'))
  assert.ok(html.includes('账户资格及剩余额度：未核验'))
  assert.ok(html.includes('非下单入口'))
  assert.ok(!html.includes('<img src=x>'))
  assert.ok(!html.includes('立即买入'))
})
