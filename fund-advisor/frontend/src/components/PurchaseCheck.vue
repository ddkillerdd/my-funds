<template>
  <div class="purchase-check" role="note">
    <template v-if="isCurrentPurchaseCheck(check, now)">
      <strong>渠道快照核验通过 · 非自动交易指令</strong>
      <div>渠道：{{ check.platform }} · {{ check.payment_method }}</div>
      <div>总付款 {{ formatRmb(check.gross_payment_rmb) }}（含申购费）</div>
      <div>申购费率 {{ check.subscription_fee_rate_pct }}% · 预计手续费 {{ formatRmb(check.estimated_fee_rmb) }}</div>
      <div>预计净投入 {{ formatRmb(check.estimated_net_investment_rmb) }}；实际份额以平台确认为准</div>
      <div>核验时间：{{ check.observed_at }} · 来源：{{ check.source }}</div>
      <p>仅比较申购费，不代表持有期总成本最低；快照会过期，下单前须重查状态和额度。</p>
    </template>
    <template v-else>
      <strong>暂不执行买入 · 保留现金</strong>
      <div>尚未通过当天渠道、账户资格、费率和额度核验。旧报告或公共网页不能代替可交易证明。</div>
      <ul v-if="check?.channels?.length">
        <li v-for="(channel, i) in check.channels" :key="i">
          {{ channel.platform || '未知平台' }}：{{ channel.reasons.map(channelReasonLabel).join('；') || '未选用' }}
        </li>
      </ul>
    </template>
    <div>所有平台共享日20元、月200元上限；不自动换基金、不预约、不下单。</div>
  </div>
</template>

<script setup>
import { channelReasonLabel, formatRmb, isCurrentPurchaseCheck } from '../utils/purchaseChannel.js'
defineProps({ check: { type: Object, default: null }, now: { type: Number, required: true } })
</script>

<style scoped>
.purchase-check { margin: 10px 0; padding: 12px; background: #f4f8fc; border-left: 3px solid #409eff; line-height: 1.8; font-size: 13px; overflow-wrap: anywhere; }
.purchase-check p { color: #606266; margin: 6px 0; }
</style>
