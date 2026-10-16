<template>
  <section class="confirmation-panel">
    <h3>核对下单页，试算含费付款</h3>
    <p>只使用当前报告，不再调用模型。请打开平台下单页核对后填写；不知道的数字留空，不能把公开费率当作账户实际优惠。</p>
    <p>不填姓名、邮箱、银行卡号、账号或密钥。不登录账户、不保存本次信息、不发送邮件，也不下单。</p>
    <fieldset :disabled="busy">
      <div class="form-grid">
        <label>本报告中的基金<select v-model="form.fund_code"><option value="">请选择</option><option v-for="item in funds" :key="item.fund_code" :value="item.fund_code">{{ item.fund_name }}（{{ item.fund_code }}）</option></select></label>
        <label>实际购买平台<select v-model="form.platform"><option value="">请选择</option><option>支付宝</option><option>天天基金</option></select></label>
        <label>支付方式（不填卡号）<select v-model="form.payment_method"><option value="">请选择</option><option v-for="method in methods" :key="method">{{ method }}</option></select></label>
        <label>当前下单页状态<select v-model="form.purchase_status"><option value="unknown">未核实</option><option value="open">开放，当前小额可以提交</option><option value="paused">暂停申购</option></select></label>
        <label>实际申购费率（%，如0.06）<input v-model="form.subscription_fee_rate_pct" type="number" min="0" max="100" step="any" placeholder="未知留空；免费须明确填0"></label>
        <label>起购额（元）<input v-model="form.min_purchase_rmb" type="number" min="0.01" step="0.01" placeholder="未知留空"></label>
        <label>已核实本次至少可付款（元，最多20）<input v-model="form.verified_capacity_rmb" type="number" min="0" max="20" step="0.01" placeholder="不是余额；未知留空"></label>
      </div>
      <label class="check-line"><input v-model="form.account_eligible" type="checkbox">我已在该平台、该支付方式确认当前账户可以申购（未确认不勾选）</label>
      <label class="check-line"><input :checked="acknowledged" type="checkbox" @change="acknowledge($event.target.checked)">以上来自我核对的下单页，不是旧截图；我理解仅作当次试算、不执行交易</label>
      <button type="button" :disabled="!acknowledged || !funds.length" @click="preview">{{ busy ? '只读复核中…' : '确认并试算（不买入）' }}</button>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="result" class="preview-result" aria-live="polite">
      <strong>{{ current ? '当次试算结果（非额度预留）' : '预览已到期或时间异常，请重新核对试算' }}</strong>
      <p>按所有平台实际付款合计复核：日最多20元、月最多200元。只补充渠道信息，不能解除冷却、预算或数据质量拦截。</p>
      <article v-for="(item, index) in result.delivery_actions" :key="index">
        <strong>{{ item.fund_name }}（{{ item.fund_code }}）</strong>
        <p v-if="current && item.payment_rmb > 0">{{ item.platform }} · {{ item.payment_method }}：总付款 {{ formatRmb(item.payment_rmb) }}（含费），预计申购费 {{ formatRmb(item.estimated_fee_rmb) }}，净投入 {{ formatRmb(item.estimated_net_investment_rmb) }}。</p>
        <p v-else>不操作 · 0.00元。{{ (item.reasons || []).map(confirmationReasonLabel).join('；') }}</p>
      </article>
      <p>来源为本次手动填写，非平台API独立核验。有效至 {{ result.valid_until }}，并非保证成交价或收益；实际扣费及确认份额以平台为准。</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { formatRmb } from '../utils/purchaseChannel.js'
import { blankPurchaseConfirmation, buildPurchaseConfirmationPayload, confirmationFundOptions, confirmationReasonLabel, isConfirmationCurrent, paymentMethods, requestPurchaseConfirmation } from '../utils/purchaseConfirmation.js'

const props = defineProps({ reportId: { type: Number, required: true }, actions: { type: Array, default: () => [] } })
const form = reactive(blankPurchaseConfirmation())
const busy = ref(false)
const acknowledged = ref(false)
const observedAt = ref('')
const error = ref('')
const result = ref(null)
const clock = ref(Date.now())
const funds = computed(() => confirmationFundOptions(props.actions))
const methods = computed(() => paymentMethods[form.platform] || [])
const current = computed(() => isConfirmationCurrent(result.value, clock.value))
let version = 0
let mounted = true
let timer = null
// 只在浏览器挂载后启动失效时钟，SSR不会创建悬挂计时器。
onMounted(() => { timer = setInterval(() => { clock.value = Date.now() }, 5000) })

// 任一字段、报告或候选变化都使旧确认和旧结果失效，不能带着旧勾选改金额。
function invalidate() {
  version += 1
  acknowledged.value = false
  observedAt.value = ''
  result.value = null
  error.value = ''
}
watch(form, invalidate, { flush: 'sync' })
watch(() => form.platform, () => { form.payment_method = '' }, { flush: 'sync' })
watch(() => [props.reportId, props.actions], invalidate)

// 时间戳只在主动勾选时记录，重复点击试算不刷新旧下单页证据。
function acknowledge(checked) {
  acknowledged.value = checked
  observedAt.value = checked ? new Date().toISOString() : ''
  result.value = null
}

// 发起一次只读试算，丢弃报告或表单改变后的迟到响应，不重试、不保存。
async function preview() {
  if (busy.value) return
  const requestVersion = ++version
  result.value = null
  error.value = ''
  busy.value = true
  try {
    const payload = buildPurchaseConfirmationPayload(form, acknowledged.value, observedAt.value)
    const data = await requestPurchaseConfirmation(props.reportId, payload)
    if (mounted && requestVersion === version) { result.value = data; clock.value = Date.now() }
  } catch (e) {
    if (mounted && requestVersion === version) error.value = e?.name === 'TimeoutError' ? '只读复核超时，未保存或下单；请重新核对。' : e.message
  } finally {
    if (mounted) busy.value = false
  }
}

// 离开页面时清理时钟并忽略在途读取，不把旧报告结果带到新报告。
onBeforeUnmount(() => { mounted = false; version += 1; clearInterval(timer) })
</script>

<style scoped>
.confirmation-panel { border: 1px solid #d9ecff; background: #f8fbff; padding: 16px; margin: 16px 0; border-radius: 8px; overflow-wrap: anywhere; }
.confirmation-panel p { color: #606266; font-size: 13px; line-height: 1.7; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
label { display: block; font-size: 13px; line-height: 1.7; }
select, input[type=number] { display: block; box-sizing: border-box; width: 100%; padding: 8px; border: 1px solid #dcdfe6; border-radius: 4px; background: white; }
.check-line { margin: 12px 0; }
button { padding: 10px 16px; color: white; background: #2876c7; border: 0; border-radius: 4px; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.preview-result { padding-top: 16px; }
article { background: white; margin: 10px 0; padding: 10px; }
</style>
