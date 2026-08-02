<template>
  <div class="simulator-view">
    <h2 class="page-title">策略回测 · 盈利能力分析</h2>

    <el-card shadow="never" class="input-card">
      <div class="fetch-row">
        <span class="label">拉取任意基金(仅本次模拟, 用后可清理)：</span>
        <el-input
          v-model="remoteCode"
          placeholder="输入基金代码, 如 110022"
          style="width: 180px"
          clearable
          @keyup.enter="fetchRemote"
        />
        <el-button type="success" plain :loading="fetching" @click="fetchRemote">
          {{ fetching ? '拉取中...' : '拉取历史' }}
        </el-button>
        <span v-if="tmpFunds.length" class="tmp-groups">
          <span class="label">已拉取临时基金：</span>
          <el-tag
            v-for="t in tmpFunds"
            :key="t.fund_code"
            size="small"
            closable
            class="tmp-tag"
            @click="useTmpFund(t)"
            @close="removeTmpFund(t)"
          >
            {{ t.fund_code }} {{ t.fund_name }}
          </el-tag>
        </span>
      </div>
      <el-divider />
      <div class="fund-row-header">
        <span class="label">选择基金与初始成本（金额即你的初始投入，可自由填写）</span>
        <el-button type="primary" size="small" @click="addFundRow">
          <el-icon><Plus /></el-icon>&nbsp;添加基金
        </el-button>
      </div>

      <div v-for="(row, idx) in fundRows" :key="idx" class="fund-row">
        <el-select
          v-model="row.fund_code"
          filterable
          placeholder="选择基金"
          style="width: 340px"
          @change="(c) => onFundChange(row, c)"
        >
          <el-option
            v-for="f in fundOptions"
            :key="f.fund_code"
            :value="f.fund_code"
            :label="`${f.fund_code} ${f.fund_name}`"
            :disabled="!f.can_backtest"
          >
            <span>{{ f.fund_code }} {{ f.fund_name }}</span>
            <span class="opt-tag" :class="f.can_backtest ? 'ok' : 'bad'">
              {{ f.can_backtest ? `${f.nav_days}天` : '历史不足' }}
            </span>
          </el-option>
        </el-select>
        <el-input-number
          v-model="row.amount"
          :min="100"
          :step="500"
          :controls-position="'right'"
          style="width: 160px"
          placeholder="金额(元)"
        />
        <span class="amount-suffix">元</span>
        <el-button
          v-if="fundRows.length > 1"
          type="danger"
          plain
          size="small"
          circle
          @click="removeFundRow(idx)"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>

      <div class="param-row">
        <span class="label">回测窗口：</span>
        <el-checkbox-group v-model="selectedWindows">
          <el-checkbox :value="30" label="30" />30天
          <el-checkbox :value="90" label="90" />90天
          <el-checkbox :value="365" label="365" />365天
        </el-checkbox-group>
        <el-button type="primary" :loading="loading" class="run-btn" @click="run">
          {{ loading ? '回测中...' : '开始回测' }}
        </el-button>
      </div>

      <div class="tip-text">
        纯量化回放（RFC-016）：把你的这套买卖信号放到历史行情里重跑，验证它到底赚不赚钱。
        模拟采用理想化执行（无费率/当日即时），侧重验证信号方向，不构成投资建议。
      </div>
    </el-card>

    <!-- ==================== 结果 ==================== -->
    <template v-if="result">
      <!-- 总结 -->
      <el-card shadow="never" class="result-card">
        <template #header>
          <div class="card-head">
            <span>📊 盈利判定总结</span>
            <span class="sub-info">
              {{ result.funds_used.length }} 只基金 · 初始 {{ fmtMoney(result.initial_amount) }} · 耗时 {{ (result.duration_seconds || 0).toFixed(1) }}s
            </span>
          </div>
        </template>

        <el-alert
          :type="summaryType"
          :title="result.summary.verdict"
          :closable="false"
          show-icon
          class="verdict"
        />

        <el-row :gutter="16" class="metric-row">
          <el-col :span="6">
            <div class="metric-card">
              <div class="metric-label">平均超额收益</div>
              <div class="metric-value" :class="pnlClass(result.summary.avg_excess_pct)">
                {{ signed(result.summary.avg_excess_pct) }}%
              </div>
              <div class="metric-sub">vs 死拿不动</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-card">
              <div class="metric-label">最佳窗口超额</div>
              <div class="metric-value" :class="pnlClass(result.summary.best_excess_pct)">
                {{ signed(result.summary.best_excess_pct) }}%
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-card">
              <div class="metric-label">最差窗口超额</div>
              <div class="metric-value" :class="pnlClass(result.summary.worst_excess_pct)">
                {{ signed(result.summary.worst_excess_pct) }}%
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="metric-card">
              <div class="metric-label">盈利可信度</div>
              <div class="metric-value" :class="confClass">
                {{ confLabel }}
              </div>
              <div class="metric-sub">跑赢 {{ result.summary.profitable_windows }}/{{ result.summary.total_windows }} 窗口</div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- 各窗口收益对比表 -->
      <el-card shadow="never" class="result-card">
        <template #header><span>📈 各窗口收益对比</span></template>
        <el-table :data="windowList" stripe>
          <el-table-column label="窗口" width="100" align="center">
            <template #default="{ row }">{{ row.window_days }}天</template>
          </el-table-column>
          <el-table-column label="区间" min-width="180">
            <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
          </el-table-column>
          <el-table-column label="策略收益" align="center" sortable>
            <template #default="{ row }">
              <span :class="pnlClass(row.strategy_return_pct)">{{ signed(row.strategy_return_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="死拿基准" align="center">
            <template #default="{ row }">
              <span :class="pnlClass(row.buy_hold_return_pct)">{{ signed(row.buy_hold_return_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="超额" align="center" sortable>
            <template #default="{ row }">
              <el-tag :type="row.excess_return_pct >= 0 ? 'success' : 'danger'" size="small">
                {{ signed(row.excess_return_pct) }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="策略最大回撤" align="center">
            <template #default="{ row }">
              <span style="color: #e6a23c">-{{ row.strategy_max_drawdown_pct }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="判定" align="center" width="140">
            <template #default="{ row }">
              <el-tag v-if="row.beats_buy_hold" type="success" size="small">跑赢死拿</el-tag>
              <el-tag v-else-if="row.is_profitable" type="warning" size="small">盈利但跑输</el-tag>
              <el-tag v-else type="danger" size="small">亏损</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 图表: 每日趋势 + 每日盈亏 -->
      <el-card shadow="never" class="result-card">
        <template #header>
          <div class="card-head">
            <span>📉 每日净值趋势与盈亏</span>
            <el-radio-group v-model="activeWindow" size="small">
              <el-radio-button
                v-for="w in windowList"
                :key="w.window_days"
                :value="w.window_days"
              >{{ w.window_days }}天</el-radio-button>
            </el-radio-group>
          </div>
        </template>

        <div v-if="activeDaily.length" class="chart-grid">
          <div class="chart-box">
            <div class="chart-title">组合总市值 vs 初始投入</div>
            <v-chart :option="valueChartOption" autoresize style="height: 280px" />
          </div>
          <div class="chart-box">
            <div class="chart-title">每日盈亏（相对前一交易日）</div>
            <v-chart :option="dailyPnlOption" autoresize style="height: 280px" />
          </div>
          <div class="chart-box">
            <div class="chart-title">累计盈亏（相对初始投入）</div>
            <v-chart :option="cumPnlOption" autoresize style="height: 280px" />
          </div>
          <div class="chart-box">
            <div class="chart-title">各基金历史净值走势
              <div class="nav-window-switch">
                <el-radio-group v-model="navWindow" size="small">
                  <el-radio-button v-for="o in navWindowOptions" :key="o.value" :value="o.value">
                    {{ o.label }}
                  </el-radio-button>
                </el-radio-group>
              </div>
            </div>
            <v-chart :option="navTrendOption" autoresize style="height: 280px" />
          </div>
        </div>
        <el-empty v-else description="该窗口历史不足，无每日数据" />
      </el-card>

      <!-- 优化建议 -->
      <el-card shadow="never" class="result-card">
        <template #header><span>💡 优化建议（以盈利为目标）</span></template>
        <el-timeline v-if="result.advice.length">
          <el-timeline-item
            v-for="(a, i) in result.advice"
            :key="i"
            :type="adviceType(a.level)"
            :hollow="true"
          >
            <div class="advice-item">
              <div class="advice-head">
                <el-tag :type="adviceTagType(a.level)" size="small">{{ a.target }}</el-tag>
                <span class="advice-msg">{{ a.message }}</span>
              </div>
              <div v-if="a.action" class="advice-action">👉 {{ a.action }}</div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无建议（历史数据不足或无回测结果）" />
      </el-card>
    </template>

    <el-empty
      v-else
      description="选择基金与金额后开始回测，查看策略的盈利能力"
      class="empty-hint"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  TooltipComponent,
  GridComponent,
  DataZoomComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Plus, Delete } from '@element-plus/icons-vue'
import {
  getSimulatorFunds,
  runSimulation,
  fetchRemoteFund,
  getTmpFunds,
  cleanupTmpFunds,
  runAdaptiveOptimize,
  getAdaptiveTask,
  getAdaptiveProposals,
  approveAdaptiveProposal,
  rejectAdaptiveProposal,
  getAdaptiveOverrides,
} from '../api/index.js'

use([
  LineChart, BarChart,
  TooltipComponent, GridComponent, DataZoomComponent, LegendComponent,
  CanvasRenderer,
])

const fundOptions = ref([])
const fundRows = ref([{ fund_code: '', amount: 5000 }])
const selectedWindows = ref([30, 90, 365])
const loading = ref(false)
const result = ref(null)
const activeWindow = ref(90)
// 第4张图(净值走势)周期切换: 6M / 1Y / ALL
const navWindow = ref('1Y')
const navWindowOptions = [
  { label: '近6月', value: '6M', days: 120 },
  { label: '近1年', value: '1Y', days: 250 },
  { label: '全部', value: 'ALL', days: 0 },
]

// 临时基金(任意代码拉取)
const remoteCode = ref('')
const fetching = ref(false)
const tmpFunds = ref([])

// ---- 自适应优化 (RFC-017) ----
const adaptiveLoading = ref(false)
const adaptiveTaskId = ref(null)
const adaptiveProgress = ref('')
const adaptiveLookback = ref(600)
const adaptiveProposals = ref([])
const adaptiveOverrides = ref([])

async function loadTmpFunds() {
  try {
    tmpFunds.value = await getTmpFunds()
    // 将临时基金并入可选列表(can_backtest=true)
    for (const t of tmpFunds.value) {
      if (!fundOptions.value.some((f) => f.fund_code === t.fund_code)) {
        fundOptions.value.push({
          fund_code: t.fund_code,
          fund_name: t.fund_name,
          latest_nav: null,
          nav_days: t.nav_days,
          can_backtest: true,
        })
      }
    }
  } catch {
    /* interceptor */
  }
}

async function fetchRemote() {
  const code = (remoteCode.value || '').trim()
  if (!code) return
  fetching.value = true
  try {
    const t = await fetchRemoteFund(code)
    remoteCode.value = ''
    await loadTmpFunds()
    // 自动加入一条回测行
    fundRows.value.unshift({ fund_code: t.fund_code, amount: 5000 })
  } catch {
    /* interceptor */
  } finally {
    fetching.value = false
  }
}

function useTmpFund(t) {
  fundRows.value.unshift({ fund_code: t.fund_code, amount: 5000 })
}

async function removeTmpFund(t) {
  try {
    await cleanupTmpFunds(0)  // 用后即删
    tmpFunds.value = tmpFunds.value.filter((x) => x.fund_code !== t.fund_code)
  } catch {
    /* interceptor */
  }
}

onMounted(async () => {
  try {
    fundOptions.value = await getSimulatorFunds()
    await loadTmpFunds()
    await loadAdaptive()
  } catch {
    /* interceptor */
  }
})

function addFundRow() {
  fundRows.value.push({ fund_code: '', amount: 5000 })
}
function removeFundRow(idx) {
  fundRows.value.splice(idx, 1)
}
function onFundChange(row, code) {
  const f = fundOptions.value.find((x) => x.fund_code === code)
  if (f && !row.amount) row.amount = 5000
}

const windowList = computed(() =>
  result.value ? Object.values(result.value.windows || {}) : []
)

const activeDaily = computed(() => {
  const w = windowList.value.find((x) => x.window_days === activeWindow.value)
  return w ? w.daily : []
})

// 净值走势图的数据源: 取所有回测窗口里历史最长的那份(通常是365天),
// 让"近6月/近1年/全部"切换有意义(不受当前 activeWindow 限制)
const navDaily = computed(() => {
  const all = windowList.value
  if (!all.length) return []
  let best = all[0]
  for (const w of all) {
    if (w.daily.length > best.daily.length) best = w
  }
  return best.daily || []
})

const summaryType = computed(() => {
  if (!result.value) return 'info'
  const s = result.value.summary
  if (s.overall_profitable && s.avg_excess_pct >= 0) return 'success'
  if (s.avg_excess_pct > 0) return 'warning'
  return 'error'
})

const confLabel = computed(() => {
  const c = result.value?.summary?.profit_confidence
  return { high: '高', medium: '中', low: '低' }[c] || '--'
})
const confClass = computed(() => {
  const c = result.value?.summary?.profit_confidence
  return { high: 'c-green', medium: 'c-orange', low: 'c-red' }[c] || ''
})

function signed(v) {
  const n = Number(v) || 0
  return (n > 0 ? '+' : '') + n.toFixed(2)
}
function pnlClass(v) {
  const n = Number(v) || 0
  if (n > 0) return 'c-green'
  if (n < 0) return 'c-red'
  return 'c-gray'
}
function fmtMoney(v) {
  const n = Number(v) || 0
  return '¥' + n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}
function adviceType(level) {
  return { success: 'success', warning: 'warning', danger: 'danger' }[level] || 'primary'
}
function adviceTagType(level) {
  return { success: 'success', warning: 'warning', danger: 'danger', info: 'info' }[level] || 'info'
}

// ---- 自适应优化方法 (RFC-017) ----
async function loadAdaptive() {
  try {
    adaptiveProposals.value = await getAdaptiveProposals()
    adaptiveOverrides.value = await getAdaptiveOverrides()
  } catch { /* interceptor */ }
}

async function runAdaptive() {
  if (adaptiveLoading.value) return
  adaptiveLoading.value = true
  adaptiveTaskId.value = null
  try {
    const funds = fundRows.value
      .filter((r) => r.fund_code)
      .map((r) => r.fund_code)
    const params = { lookback_days: adaptiveLookback.value }
    if (funds.length) {
      params.fund_codes = funds
    }
    const { task_id } = await runAdaptiveOptimize(params)
    adaptiveTaskId.value = task_id
    pollAdaptive(task_id)
  } catch { /* interceptor */ } finally {
    adaptiveLoading.value = false
  }
}

async function pollAdaptive(taskId, tries = 0) {
  try {
    const st = await getAdaptiveTask(taskId)
    adaptiveTaskId.value = taskId
    adaptiveProgress.value = st.progress || ''
    if (st.status === 'done' || st.status === 'error') {
      adaptiveTaskId.value = null
      adaptiveLoading.value = false
      if (st.status === 'done') await loadAdaptive()
    } else if (tries < 120) {
      setTimeout(() => pollAdaptive(taskId, tries + 1), 3000)
    }
  } catch {
    adaptiveTaskId.value = null
    adaptiveLoading.value = false
  }
}

async function approveProposal(p) {
  try {
    await approveAdaptiveProposal(p.id, '')
    await loadAdaptive()
  } catch { /* interceptor */ }
}

async function rejectProposal(p) {
  try {
    await rejectAdaptiveProposal(p.id, '')
    await loadAdaptive()
  } catch { /* interceptor */ }
}

function clsLabel(cls) {
  return { low: '低波动', medium: '中波动', high: '高波动' }[cls] || cls
}
function riskTag(cls) {
  return { low: 'success', medium: 'warning', high: 'danger' }[cls] || 'info'
}

async function run() {
  const funds = fundRows.value
    .filter((r) => r.fund_code)
    .map((r) => ({ fund_code: r.fund_code, amount: r.amount || 0 }))
  if (!funds.length) {
    return
  }
  loading.value = true
  try {
    result.value = await runSimulation({
      funds,
      windows: selectedWindows.value,
    })
    activeWindow.value = selectedWindows.value.includes(90)
      ? 90
      : selectedWindows.value[selectedWindows.value.length - 1]
  } catch {
    /* interceptor */
  } finally {
    loading.value = false
  }
}

// ---- 图表 option ----
const baseTooltip = {
  trigger: 'axis',
  axisPointer: { type: 'cross' },
  valueFormatter: (v) => (typeof v === 'number' ? v.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : v),
}

const valueChartOption = computed(() => {
  const dates = activeDaily.value.map((d) => d.date)
  const values = activeDaily.value.map((d) => d.total_value)
  const init = result.value?.initial_amount || 0
  const baseline = dates.map(() => init)
  return {
    tooltip: baseTooltip,
    legend: { data: ['策略总市值', '初始投入'], top: 0 },
    grid: { left: 70, right: 20, top: 30, bottom: 60 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30, fontSize: 11 } },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v) => '¥' + (v >= 10000 ? (v / 10000).toFixed(1) + '万' : v) },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series: [
      {
        name: '策略总市值',
        type: 'line',
        data: values,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#409eff' },
        areaStyle: { opacity: 0.12 },
        markLine: {
          silent: true,
          data: [{ yAxis: init, name: '初始投入' }],
          lineStyle: { type: 'dashed', color: '#909399' },
        },
      },
      { name: '初始投入', type: 'line', data: baseline, showSymbol: false, lineStyle: { type: 'dashed', color: '#909399' } },
    ],
  }
})

const dailyPnlOption = computed(() => {
  const dates = activeDaily.value.map((d) => d.date)
  const pnl = activeDaily.value.map((d) => d.daily_pnl)
  return {
    tooltip: baseTooltip,
    grid: { left: 70, right: 20, top: 20, bottom: 60 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30, fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v) => '¥' + v } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series: [
      {
        type: 'bar',
        data: pnl,
        itemStyle: {
          color: (p) => (p.value >= 0 ? '#67c23a' : '#f56c6c'),
        },
      },
    ],
  }
})

const cumPnlOption = computed(() => {
  const dates = activeDaily.value.map((d) => d.date)
  const cum = activeDaily.value.map((d) => d.cumulative_pnl)
  return {
    tooltip: { ...baseTooltip, valueFormatter: (v) => '¥' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
    grid: { left: 70, right: 20, top: 20, bottom: 60 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30, fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v) => '¥' + v } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series: [
      {
        type: 'line',
        data: cum,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#e6a23c' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(230,162,60,0.25)' },
              { offset: 1, color: 'rgba(230,162,60,0.02)' },
            ],
          },
        },
      },
    ],
  }
})

// 各基金历史净值走势(可切换周期, 归一化到100, 便于并排对比涨跌幅度)
const navTrendOption = computed(() => {
  const all = navDaily.value
  if (!all.length) {
    return { series: [] }
  }
  // 按所选周期截取数据段
  const days = navWindowOptions.find((o) => o.value === navWindow.value)?.days || 0
  const slice = days > 0 ? all.slice(-days) : all  // 近6月/近1年 | 全部
  const dates = slice.map((d) => d.date)
  // 收集该周期内出现的所有基金code
  const codes = []
  for (const d of slice) {
    for (const c of Object.keys(d.nav || {})) {
      if (!codes.includes(c)) codes.push(c)
    }
  }
  const nameOf = (c) => {
    const f = fundOptions.value.find((x) => x.fund_code === c)
    const u = (result.value?.funds_used || []).find((x) => x.fund_code === c)
    return (f?.fund_name || u?.fund_name || c) + ' ' + c
  }
  const palette = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9254de', '#13c2c2', '#fa8c16']
  const series = codes.map((c, i) => {
    // 归一化: 以该周期首日净值为 100, 与支付宝同口径可比
    const first = slice.find((d) => d.nav && d.nav[c] != null)
    const base = first ? Number(first.nav[c]) : 1
    const data = slice.map((d) => {
      const v = d.nav && d.nav[c]
      return v != null && base > 0 ? +(Number(v) / base * 100).toFixed(2) : null
    })
    return {
      name: nameOf(c),
      type: 'line',
      data,
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2, color: palette[i % palette.length] },
    }
  })
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v) => (v == null ? '-' : v.toFixed(2)) },
    legend: { top: 0, type: 'scroll' },
    grid: { left: 70, right: 20, top: 40, bottom: 60 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30, fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v) => v.toFixed(0) } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series,
  }
})
</script>

<style scoped>
.page-title { margin-top: 0; }
.input-card { margin-bottom: 16px; }
.fetch-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
}
.tmp-groups {
  margin-left: 16px;
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.tmp-tag { cursor: pointer; }
.tmp-tag:hover { opacity: 0.85; }
.fund-row-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.fund-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.label { color: #606266; font-size: 14px; }
.amount-suffix { color: #909399; font-size: 13px; }
.param-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin: 16px 0 8px;
}
.run-btn { margin-left: auto; }
.tip-text { color: #909399; font-size: 12px; margin-top: 8px; }
.opt-tag {
  float: right;
  font-size: 12px;
  margin-left: 12px;
}
.opt-tag.ok { color: #67c23a; }
.opt-tag.bad { color: #f56c6c; }
.result-card { margin-bottom: 16px; }
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.sub-info { color: #909399; font-size: 12px; }
.verdict { margin-bottom: 16px; }
.metric-row { margin-top: 4px; }
.metric-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 14px;
  text-align: center;
}
.metric-label { color: #909399; font-size: 12px; margin-bottom: 6px; }
.metric-value { font-size: 24px; font-weight: 700; }
.metric-sub { color: #909399; font-size: 12px; margin-top: 4px; }
.c-green { color: #67c23a; }
.c-red { color: #f56c6c; }
.c-orange { color: #e6a23c; }
.c-gray { color: #909399; }
.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.chart-box { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px; }
.chart-title {
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.nav-window-switch { flex-shrink: 0; }
.advice-item { padding-left: 4px; }
.advice-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.advice-msg { color: #303133; font-size: 14px; }
.advice-action { margin-top: 6px; color: #909399; font-size: 13px; }
.empty-hint { margin-top: 40px; }
</style>
