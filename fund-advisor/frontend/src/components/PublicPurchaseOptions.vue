<template>
  <el-card shadow="never" class="public-options">
    <div class="query-header">
      <strong>其他平台公开申购信息</strong>
      <el-button :loading="loading" @click="$emit('query')">查询当前持仓（只读）</el-button>
    </div>
    <p>仅查询当前四只基金的天天基金公开页面，不登录账户、不预约、不下单。公开费率不等于你的实际优惠，也不能确认你的剩余额度。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!items.length">点击查询后显示公开线索；未查到或字段不完整时保持“未知”，不会沿用旧费率。</p>
    <section v-for="item in items" :key="item.fund_code" class="public-item">
      <strong>{{ item.fund_code }} · 天天基金</strong>
      <p>公开状态：{{ statusLabel(item.purchase_status) }} · 账户资格及剩余额度：未核验</p>
      <p>公开小额申购费率：{{ feeLabel(item.subscription_fee_rate_pct) }} · 起购额：{{ formatRmb(item.min_purchase_rmb) }}</p>
      <p>抓取时间：{{ item.observed_at || '未取得' }}（不是公告生效时间或账户确认时间）</p>
      <p v-if="item.error_kind">部分信息未能可靠取得，请以平台下单确认页为准。</p>
      <a :href="publicSourceUrl(item.fund_code)" target="_blank" rel="noopener noreferrer">查看公开来源（非下单入口）</a>
    </section>
    <p>这里只比较公开申购费，不是持有期总费用排名；暂停申购不自动改为预约，也不自动推荐另一只基金。</p>
  </el-card>
</template>

<script setup>
import { formatRmb, publicSourceUrl, publicStatusLabel as statusLabel, publicFeeLabel as feeLabel } from '../utils/purchaseChannel.js'

defineProps({ items: { type: Array, default: () => [] }, loading: Boolean, error: String })
defineEmits(['query'])
</script>

<style scoped>
.public-options { margin-bottom: 16px; overflow-wrap: anywhere; }
.query-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.public-options p { color: #606266; font-size: 13px; line-height: 1.7; }
.public-item { border-left: 3px solid #409eff; background: #f0f9ff; margin: 12px 0; padding: 12px; }
.public-item a { color: #2876c7; font-size: 13px; }
</style>
