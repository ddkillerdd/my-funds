<template>
  <div class="advisor-view">
    <h2 class="page-title">AI 投资顾问</h2>

    <!-- Status & Actions -->
    <el-card shadow="never" class="action-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="12">
          <div class="status-info">
            <el-tag v-if="apiConfigured" type="success" size="small">AI 已配置</el-tag>
            <el-tag v-else type="danger" size="small">AI 未配置</el-tag>
            <span v-if="activeReportTime" class="last-gen">
              当前报告: {{ activeReportTime }}
            </span>
            <span class="capital-wrap">
              <span class="capital-label">可用增量资金(¥)</span>
              <el-input-number
                v-model="totalCapital"
                :min="0"
                :step="1000"
                :controls="false"
                size="small"
                placeholder="未设置"
                style="width: 130px"
                @change="saveTotalCapital"
              />
            </span>
          </div>
        </el-col>
        <el-col :span="12" style="text-align: right">
          <el-button type="primary" :icon="Promotion" :loading="loading" @click="runAnalysis">
            {{ loading ? '分析中...' : '生成新报告' }}
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Report History Drawer / Sidebar -->
    <el-row :gutter="16">
      <el-col :span="6">
        <el-card shadow="never" class="history-card">
          <template #header>
            <div class="section-header">
              <el-icon :size="18"><Tickets /></el-icon>
              <span>历史报告（{{ reportHistoryTotal }}）</span>
            </div>
          </template>
          <div v-if="reportHistory.length === 0" class="empty-hint">
            暂无历史报告
          </div>
          <div v-else class="history-list">
            <div
              v-for="item in reportHistory"
              :key="item.id"
              class="history-item"
              :class="{ active: item.id === activeReportId }"
              @click="loadReportById(item.id)"
            >
              <div class="history-date">{{ formatTime(item.created_at) }}</div>
              <div class="history-model">
                <el-tag size="small" effect="plain">{{ item.model }}</el-tag>
              </div>
            </div>
            <div v-if="hasMoreHistory" class="history-more" @click="loadMoreHistory">
              加载更多...
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="18">
        <!-- Loading State -->
        <el-skeleton v-if="loading && !report" :rows="8" animated class="skeleton-card" />

        <!-- Error State -->
        <el-alert
          v-if="error"
          :title="error"
          type="warning"
          show-icon
          :closable="true"
          @close="error = ''"
        />

        <!-- No Report State -->
        <el-empty v-if="!loading && !report && !activeReportId" description="没有分析报告，点击右侧按钮生成" />

        <!-- Report Content -->
        <template v-if="report">
          <!-- Market Analysis -->
          <el-card shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><Promotion /></el-icon>
                <span>市场环境分析</span>
              </div>
            </template>
            <div class="market-analysis">
              <el-row :gutter="16">
                <el-col :span="8">
                  <div class="analysis-item">
                    <label>趋势判断</label>
                    <span class="value">{{ report.market_analysis.trend }}</span>
                  </div>
                </el-col>
                <el-col :span="16">
                  <div class="analysis-item">
                    <label>总体判断</label>
                    <span class="value">{{ report.market_analysis.overall }}</span>
                  </div>
                </el-col>
              </el-row>
              <div v-if="report.market_analysis.key_signals?.length" class="signals">
                <label>关键信号</label>
                <el-tag
                  v-for="(s, i) in report.market_analysis.key_signals"
                  :key="i"
                  size="small"
                  style="margin: 2px 4px 2px 0"
                >
                  {{ s }}
                </el-tag>
              </div>
            </div>
          </el-card>

          <!-- RFC-012 回测 / 在线学习命中率 -->
          <el-card v-if="backtestStats" shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><TrendCharts /></el-icon>
                <span>历史建议回测（在线学习）</span>
              </div>
            </template>
            <div class="backtest-block">
              <div class="backtest-grid">
                <div class="backtest-cell">
                  <div class="bt-num">{{ backtestStats.directional }}</div>
                  <div class="bt-label">方向建议数</div>
                </div>
                <div class="backtest-cell">
                  <div class="bt-num">{{ backtestStats.validated }}</div>
                  <div class="bt-label">已验证</div>
                </div>
                <div class="backtest-cell">
                  <div class="bt-num" :class="{ 'bt-good': (backtestStats.hit_rate||0) >= 0.5, 'bt-bad': (backtestStats.hit_rate||0) < 0.5 && backtestStats.hit_rate !== null }">
                    {{ backtestStats.hit_rate !== null ? Math.round(backtestStats.hit_rate*100) + '%' : '—' }}
                  </div>
                  <div class="bt-label">整体命中率(相对沪深300)</div>
                </div>
              </div>
              <div v-if="Object.keys(backtestStats.by_action||{}).length" class="by-action">
                <el-tag
                  v-for="(v, k) in backtestStats.by_action"
                  :key="k"
                  :type="(v.hit_rate||0)>=0.5 ? 'success' : 'warning'"
                  size="small"
                  style="margin: 2px 6px 2px 0"
                >
                  {{ k }}: {{ Math.round((v.hit_rate||0)*100) }}% ({{ v.hits }}/{{ v.total }})
                </el-tag>
              </div>
              <div v-if="backtestStats && report && report.backtest_feedback" class="bt-hint">
                <el-alert type="info" :closable="false" :title="report.backtest_feedback.prompt_hint" />
              </div>
              <div v-else-if="backtestStats.directional===0" class="bt-empty">
                尚无已回测建议——系统会在每次报告生成后记录建议，积累足够样本后自动校准置信度（每10天适应）。
              </div>
            </div>
          </el-card>

          <!-- Holdings Health -->
          <el-card shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><List /></el-icon>
                <span>持仓健康度</span>
              </div>
            </template>
            <div v-if="!report.holdings_health?.length" class="empty-hint">
              暂无持仓数据或 AI 分析不可用
            </div>
            <div v-else class="health-list">
              <div
                v-for="h in report.holdings_health"
                :key="h.fund_code"
                class="health-item"
              >
                <el-row :gutter="16" align="middle">
                  <el-col :span="8">
                    <strong>{{ h.fund_code }}</strong>
                    <span class="fund-name">{{ h.fund_name }}</span>
                  </el-col>
                  <el-col :span="4">
                    <el-progress
                      :percentage="h.health_score"
                      :color="healthColor(h.health_score)"
                      :stroke-width="14"
                    />
                  </el-col>
                  <el-col :span="6">
                    <span class="concern-text" v-if="h.concerns">{{ cleanConcerns(h.concerns) }}</span>
                  </el-col>
                  <el-col :span="6">
                    <span class="suggestion-text" v-if="h.suggestion_label || h.suggestion">
                      {{ h.suggestion_label || actionLabel(h.suggestion) }}
                      <template v-if="h.target_weight_pct != null">
                        <span class="target-wt">目标{{ h.target_weight_pct }}%</span>
                      </template>
                    </span>
                  </el-col>
                </el-row>
              </div>
            </div>
          </el-card>

          <!-- Action Recommendations -->
          <el-card shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><Warning /></el-icon>
                <span>操作建议</span>
              </div>
            </template>
            <div v-if="!report.actions?.length" class="empty-hint">
              暂无建议
            </div>
            <div v-else class="action-list">
              <el-timeline>
                <el-timeline-item
                  v-for="(a, i) in report.actions"
                  :key="i"
                  :type="actionType(a.action)"
                  :hollow="true"
                >
                  <div class="action-item">
                    <div class="action-header">
                      <strong>{{ a.fund_name }}</strong>
                      <span class="action-badge">{{ a.action_label || actionLabel(a.action) }}</span>
                      <el-tag v-if="a.priority === 'high'" type="danger" size="small">高优</el-tag>
                      <el-tag v-else-if="a.priority === 'medium'" type="warning" size="small">中</el-tag>
                      <el-tag v-if="a.target_weight_pct != null" type="info" size="small">目标 {{ a.target_weight_pct }}%</el-tag>
                    </div>
                    <p class="action-reason">{{ cleanEvidence(a.reason) }}</p>
                    <!-- RFC-014: 绝对操作金额 -->
                    <p v-if="a.action_amount != null && a.action_amount !== 0" class="action-amount" :class="a.action_amount > 0 ? 'amt-in' : 'amt-out'">
                      {{ a.action_amount > 0 ? '▶ $' : '◀ $' }} {{ fmtMoney(Math.abs(a.action_amount)) }}
                      <template v-if="a.current_amount != null">（现持 {{ fmtMoney(a.current_amount) }} → 目标 {{ fmtMoney(a.target_amount) }}）</template>
                    </p>
                    <p v-else-if="a.action_amount === 0" class="action-amount amt-zero">无需资金变动</p>
                    <!-- RFC-020 块C: 记录实际怎么操作 -->
                    <div class="exec-row">
                      <span class="exec-label">我实际：</span>
                      <el-select
                        v-model="execSelections[a.fund_code]"
                        placeholder="选择操作"
                        size="small"
                        style="width: 110px"
                        clearable
                        @change="(v) => saveExec(a, v)"
                      >
                        <el-option label="照做" value="same_as_suggest" />
                        <el-option label="加仓" value="increase" />
                        <el-option label="减仓" value="reduce" />
                        <el-option label="未操作" value="none" />
                        <el-option label="反向" value="reversed" />
                      </el-select>
                    </div>
                  </div>
                </el-timeline-item>
              </el-timeline>
            </div>
          </el-card>

          <!-- RFC-020 块3: 盘中短线(择时)速览 -->
          <el-card v-if="report.intraday_view && Object.keys(report.intraday_view).length" shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><TrendCharts /></el-icon>
                <span>盘中择时速览</span>
                <span class="intraday-note">今日指数实时 · 仅参考方向感，不影响核心金额</span>
              </div>
            </template>
            <div class="intraday-grid">
              <div v-for="(iv, code) in report.intraday_view" :key="code" class="intraday-item">
                <div class="intraday-fund">{{ fundCodeName(code) }}</div>
                <div class="intraday-idx">{{ iv.index }}</div>
                <div class="intraday-pct" :class="(iv.pct_today ?? 0) >= 0 ? 'pct-up' : 'pct-dn'">
                  {{ iv.pct_today != null ? (iv.pct_today > 0 ? '+' : '') + iv.pct_today + '%' : '—' }}
                </div>
                <el-tag :type="iv.signal === 'oversold' ? 'success' : (iv.signal === 'overbought' ? 'danger' : 'info')" size="small">
                  {{ iv.execution_advice || '观望' }}
                </el-tag>
                <div v-if="iv.vs_ma5 != null" class="intraday-ma">vs5日线 {{ iv.vs_ma5 > 0 ? '+' : '' }}{{ iv.vs_ma5 }}%</div>
              </div>
            </div>
          </el-card>

          <!-- Portfolio Diagnosis -->
          <el-card shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><DataAnalysis /></el-icon>
                <span>组合诊断</span>
              </div>
            </template>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="集中度风险">
                {{ report.portfolio_diagnosis.concentration_risk }}
              </el-descriptions-item>
              <el-descriptions-item label="调仓建议">
                {{ report.portfolio_diagnosis.rebalance_suggestion }}
              </el-descriptions-item>
              <el-descriptions-item label="整体评价">
                {{ report.portfolio_diagnosis.overall_assessment }}
              </el-descriptions-item>
              <el-descriptions-item v-if="report.portfolio_diagnosis.strength" label="最大优势">
                {{ report.portfolio_diagnosis.strength }}
              </el-descriptions-item>
              <el-descriptions-item v-if="report.portfolio_diagnosis.weakness" label="最大弱点">
                {{ report.portfolio_diagnosis.weakness }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- RFC-021: 增量资金分配 -->
          <el-card v-if="report.incremental_allocation" shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><Money /></el-icon>
                <span>增量资金分配</span>
              </div>
            </template>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="目标盘子">
                {{ fmtMoney(report.incremental_allocation.total_scale) }} 元
                <span class="dim-hint">= 现有持仓 + 可用增量资金</span>
              </el-descriptions-item>
              <el-descriptions-item label="可用增量资金">
                {{ fmtMoney(report.incremental_allocation.available_capital) }} 元
              </el-descriptions-item>
              <el-descriptions-item label="本次已分配过金">
                {{ fmtMoney(report.incremental_allocation.allocated_capital) }} 元
                <span v-if="!report.incremental_allocation.fully_allocated" class="amt-out">（增量不足, 已按风险配比压缩）</span>
              </el-descriptions-item>
              <el-descriptions-item label="分配说明" v-if="report.incremental_allocation.notes && report.incremental_allocation.notes.length">
                <template v-for="(n, i) in report.incremental_allocation.notes" :key="i">
                  <div>{{ n }}</div>
                </template>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- Debate Verdict -->
          <el-card v-if="report.debate_verdict" shadow="hover" class="section-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><WarnTriangleFilled v-if="!report.debate_verdict.passed" /><CircleCheckFilled v-else /></el-icon>
                <span>跨模型验证</span>
                <el-tag v-if="report.debate_verdict.severity === 'high'" type="danger" size="small">严重</el-tag>
                <el-tag v-else-if="report.debate_verdict.severity === 'medium'" type="warning" size="small">中等</el-tag>
                <el-tag v-else type="success" size="small">通过</el-tag>
              </div>
            </template>
            <div v-if="report.debate_verdict.issues?.length" class="issues-list">
              <div v-for="(iss, i) in report.debate_verdict.issues" :key="i" class="issue-item">
                <el-tag v-if="iss.fund_code" size="small" style="margin-right: 4px">{{ iss.fund_code }}</el-tag>
                <span>{{ iss.finding }}</span>
                <p v-if="iss.fix_suggestion" class="issue-fix">→ {{ iss.fix_suggestion }}</p>
              </div>
            </div>
            <div v-if="report.debate_verdict.arbiter?.rationale" class="arbiter-rationale">
              <strong>裁决:</strong> {{ report.debate_verdict.arbiter.rationale }}
            </div>
            <p v-if="!report.debate_verdict.issues?.length && !report.debate_verdict.arbiter?.rationale" class="empty-hint">
              {{ report.debate_verdict.recommendation || '验证通过' }}
            </p>
          </el-card>

          <!-- Ground Truth -->
          <el-card v-if="report.ground_truth" shadow="hover" class="section-card ground-truth-card">
            <template #header>
              <div class="section-header">
                <el-icon :size="20"><Histogram /></el-icon>
                <span>客观数据 (Ground Truth)</span>
              </div>
            </template>
            <el-row :gutter="16" class="ground-truth-stats">
              <el-col :span="6">
                <div class="gt-stat-item">
                  <label>总市值</label>
                  <span class="gt-value">¥{{ report.ground_truth.total_market_value?.toFixed(0) }}</span>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="gt-stat-item">
                  <label>总盈亏</label>
                  <span :class="['gt-value', report.ground_truth.total_pnl >= 0 ? 'positive' : 'negative']">
                    {{ report.ground_truth.total_pnl >= 0 ? '+' : '' }}{{ report.ground_truth.total_pnl?.toFixed(2) }}
                  </span>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="gt-stat-item">
                  <label>集中度(Top 3)</label>
                  <span class="gt-value" :class="{ 'gt-warn': report.ground_truth.concentration_top3 > 60 }">
                    {{ report.ground_truth.concentration_top3 }}%
                  </span>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="gt-stat-item">
                  <label>{{ report.ground_truth.trend_state }}</label>
                  <span class="gt-value" :class="{ positive: report.ground_truth.trend_return > 0, negative: report.ground_truth.trend_return < 0 }">
                    {{ report.ground_truth.trend_return > 0 ? '+' : '' }}{{ report.ground_truth.trend_return?.toFixed(1) }}%
                  </span>
                </div>
              </el-col>
            </el-row>
            <div v-if="report.ground_truth.per_fund_summary?.length" class="gt-fund-list">
              <div v-for="f in report.ground_truth.per_fund_summary" :key="f.fund_code" class="gt-fund-row">
                <strong>{{ f.fund_code }}</strong>
                <span class="gt-fund-name">{{ f.fund_name }}</span>
                <span class="gt-fund-data">占比 {{ f.mv_ratio }}% | 盈亏 {{ f.pnl_pct >= 0 ? '+' : '' }}{{ f.pnl_pct?.toFixed(2) }}% | 净值变动 {{ f.nav_change_pct >= 0 ? '+' : '' }}{{ f.nav_change_pct?.toFixed(2) }}%</span>
              </div>
            </div>
          </el-card>

          <!-- Footer -->
          <div class="report-footer">
            报告生成于 {{ report.generated_at }} | 模型: {{ report.model }}
            <span v-if="report.analysis_duration_seconds"> | 耗时: {{ report.analysis_duration_seconds }}s</span>
          </div>
        </template>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Promotion, List, Warning, DataAnalysis, Tickets, WarnTriangleFilled, CircleCheckFilled, Histogram, TrendCharts, Money } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const report = ref(null)
const error = ref('')
const apiConfigured = ref(false)
const activeReportId = ref(null)
const activeReportTime = ref('')

// History state
const reportHistory = ref([])
const reportHistoryTotal = ref(0)
const historySkip = ref(0)
const hasMoreHistory = ref(false)
const backtestStats = ref(null)
const HISTORY_LIMIT = 20
// RFC-020: 总资金(前端可调, 每次分析作为绝对金额定价基准)
const totalCapital = ref(null)
// RFC-020 块C: 实际操作记录 (fund_code → 用户回填选择)
const execSelections = ref({})
const reportDate = computed(() => {
  // activeReportTime 形如 '2026-08-03 21:20:00'; 取前10位作报告日期
  const t = activeReportTime.value || ''
  return t ? String(t).slice(0, 10) : new Date().toISOString().slice(0, 10)
})

function healthColor(score) {
  if (score >= 70) return '#67c23a'
  if (score >= 40) return '#e6a23c'
  return '#f56c6c'
}

function actionType(action) {
  if (action === 'add' || action === 'increase') return 'primary'
  if (action === 'reduce' || action === 'decrease') return 'danger'
  if (action === 'watch') return 'warning'
  return 'info'
}

function fundCodeName(code) {
  const repsrc = report.value
  const hh = repsrc?.holdings_health || []
  const found = hh.find(h => h.fund_code === code)
  return found?.fund_name || code
}

function actionLabel(action) {
  const labels = {
    buy: '买入',
    add: '加仓',
    increase: '加仓',
    reduce: '减仓',
    decrease: '减仓',
    sell: '卖出',
    hold: '持有',
    watch: '关注',
  }
  return labels[action] || action
}

function fmtMoney(v) {
  if (v == null || isNaN(v)) return '-'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) + ' 元'
}

function cleanConcerns(text) {
  return cleanEvidence(text)
}

function cleanEvidence(text) {
  if (!text) return ''
  // 去掉括号内证据引用: (42.68%)  (MACD柱=-0.00)  (-0.0623)  （年化波动率=15.72%）
  // 分两步：先删英文括号，再删中文括号
  return text
    .replace(/\([^)]*(?:[=≈]|[-+]?\d)[^)]*\)/g, '')
    .replace(/（[^）]*(?:[=≈]|[-+]?\d)[^）]*）/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function runAnalysis() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/advisor/analyze', { method: 'POST' })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    report.value = data
    activeReportTime.value = data.generated_at
    activeReportId.value = null
    ElMessage.success('分析完成，报告已保存')
    // Refresh history + backtest stats
    await loadHistory()
    await loadBacktestStats()
  } catch (e) {
    error.value = '分析请求失败: ' + e.message
    ElMessage.error('分析失败')
  } finally {
    loading.value = false
  }
}

async function loadBacktestStats() {
  try {
    const resp = await fetch('/api/backtest/stats')
    if (!resp.ok) return
    backtestStats.value = await resp.json()
  } catch {
    backtestStats.value = null
  }
}

async function loadReportById(id) {
  loading.value = true
  error.value = ''
  activeReportId.value = id
  try {
    const resp = await fetch(`/api/advisor/report/${id}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    if (data.found) {
      report.value = data.report
      activeReportTime.value = data.generated_at
      // RFC-020 块C: 加载该报告下已有的实际操作记录
      execSelections.value = {}
      loadExecutions()
    } else {
      error.value = data.message || '报告加载失败'
      report.value = null
    }
  } catch (e) {
    error.value = '加载报告失败: ' + e.message
    report.value = null
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  try {
    const resp = await fetch(`/api/advisor/reports?skip=0&limit=${HISTORY_LIMIT}`)
    if (!resp.ok) return
    const data = await resp.json()
    reportHistory.value = data.items
    reportHistoryTotal.value = data.total
    historySkip.value = data.items.length
    hasMoreHistory.value = data.total > data.items.length
  } catch {
    // silent
  }
}

async function loadMoreHistory() {
  try {
    const resp = await fetch(`/api/advisor/reports?skip=${historySkip.value}&limit=${HISTORY_LIMIT}`)
    if (!resp.ok) return
    const data = await resp.json()
    reportHistory.value = [...reportHistory.value, ...data.items]
    historySkip.value += data.items.length
    hasMoreHistory.value = data.total > historySkip.value
  } catch {
    // silent
  }
}

// RFC-021: 读取/保存「可用增量资金」(本次愿投入的子弹, 下次分析动态生效)
async function loadTotalCapital() {
  try {
    const resp = await fetch('/api/config/available-capital')
    if (!resp.ok) return
    const data = await resp.json()
    totalCapital.value = data.available_capital != null ? data.available_capital : null
  } catch {
    // silent
  }
}
async function saveTotalCapital(val) {
  try {
    const resp = await fetch('/api/config/available-capital', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: val, note: '用户前端设置可用增量资金' }),
    })
    if (!resp.ok) throw new Error('保存失败')
    const data = await resp.json()
    totalCapital.value = data.available_capital
    ElMessage.success('可用增量资金已更新, 下次分析按新资金计算加仓金额')
  } catch (e) {
    ElMessage.error('可用增量资金保存失败: ' + e.message)
  }
}

// RFC-020 块C: 记录/回填“实际怎么操作”
async function saveExec(action, val) {
  if (!val) return
  if (!report.value?.actions?.length) {
    ElMessage.warning('请先生成/加载报告')
    return
  }
  const reportId = activeReportId.value ?? null
  if (!reportId) {
    ElMessage.warning('当前报告未持久化, 请从历史记录加载后再记录')
    return
  }
  try {
    const resp = await fetch('/api/trade-execution/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        report_id: reportId,
        report_date: reportDate.value,
        fund_code: action.fund_code,
        fund_name: action.fund_name || action.fund_code,
        actual_action: val,
        actual_amount: null,
        note: '前端回填',
      }),
    })
    if (!resp.ok) throw new Error('保存失败')
    ElMessage.success('已记录实际操作')
  } catch (e) {
    ElMessage.error('记录失败: ' + e.message)
  }
}

// 加载某报告下已有的实际操作记录, 回填 execSelections
async function loadExecutions() {
  const reportId = activeReportId.value ?? null
  if (!reportId) return
  try {
    const resp = await fetch(`/api/trade-execution/report/${reportId}`)
    if (!resp.ok) return
    const data = await resp.json()
    const sel = {}
    for (const r of data.records || []) {
      if (r.actual_action) sel[r.fund_code] = r.actual_action
    }
    execSelections.value = sel
  } catch { /* silent */ }
}

onMounted(async () => {
  // RFC-020: 加载总资金配置
  await loadTotalCapital()

  // RFC-012 backtest stats
  await loadBacktestStats()

  // Load history list
  await loadHistory()

  // Try to load the latest report
  try {
    const resp = await fetch('/api/advisor/report')
    if (!resp.ok) return
    const data = await resp.json()
    if (data.found && data.report) {
      report.value = data.report
      activeReportTime.value = data.generated_at
    }
  } catch {
    // silent
  }

  // Check AI config status
  try {
    const resp = await fetch('/api/advisor/status')
    const data = await resp.json()
    apiConfigured.value = data.configured
  } catch {
    // ignored
  }
})
</script>

<style scoped>
.advisor-view {
  padding: 4px;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.action-card {
  margin-bottom: 16px;
}

.status-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.last-gen {
  color: #409eff;
  font-size: 12px;
}

.capital-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 4px;
}
.capital-label {
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
}

.dim-hint {
  font-size: 12px;
  color: #909399;
  margin-left: 6px;
}

.exec-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.exec-label {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

.intraday-note {
  font-size: 12px;
  color: #909399;
  margin-left: 10px;
  font-weight: normal;
}
.intraday-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.intraday-item {
  padding: 8px 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.intraday-fund {
  font-weight: 600;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.intraday-idx {
  font-size: 12px;
  color: #909399;
  margin: 2px 0;
}
.intraday-pct {
  font-size: 16px;
  font-weight: 700;
}
.intraday-pct.pct-up { color: #f56c6c; }
.intraday-pct.pct-dn { color: #67c23a; }
.intraday-ma {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.skeleton-card {
  margin-bottom: 16px;
}

.section-card {
  margin-bottom: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 16px;
}

/* History sidebar */
.history-card {
  min-height: 400px;
}

.history-list {
  max-height: 600px;
  overflow-y: auto;
}

.history-item {
  padding: 10px 8px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.history-item:hover {
  background-color: #f5f7fa;
}

.history-item.active {
  background-color: #ecf5ff;
  border-left: 3px solid #409eff;
}

.history-date {
  font-size: 13px;
  color: #303133;
  margin-bottom: 4px;
}

.history-model {
  font-size: 11px;
}

.history-more {
  text-align: center;
  padding: 10px;
  color: #409eff;
  cursor: pointer;
  font-size: 13px;
}

.history-more:hover {
  background-color: #f5f7fa;
}

/* Report sections */
.market-analysis {
  padding: 4px 0;
}

.analysis-item {
  margin-bottom: 12px;
}

.analysis-item label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.analysis-item .value {
  font-size: 14px;
  color: #303133;
}

.signals {
  margin-top: 12px;
}

.signals label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.empty-hint {
  color: #909399;
  text-align: center;
  padding: 24px 0;
}

.health-list {
  padding: 4px 0;
}

.health-item {
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
}

.health-item:last-child {
  border-bottom: none;
}

.fund-name {
  display: block;
  font-size: 12px;
  color: #909399;
}

.concern-text {
  color: #e6a23c;
  font-size: 13px;
}

.suggestion-text {

  color: #409eff;
  font-size: 13px;
}

.target-wt {
  color: #909399;
  font-size: 12px;
  margin-left: 6px;
}

.action-amount {
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 600;
}

.amt-in {
  color: #f56c6c;
}

.amt-out {
  color: #67c23a;
}

.amt-zero {
  color: #909399;
  font-weight: 400;
}

.action-list {
  padding: 4px 0;
}

.action-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.action-badge {
  font-size: 13px;
  color: #606266;
}

.action-reason {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.report-footer {
  text-align: center;
  color: #909399;
  font-size: 12px;
  padding: 16px 0 8px 0;
}

/* Ground Truth */
.ground-truth-card {
  background-color: #fafbfc;
}

.ground-truth-stats {
  margin-bottom: 12px;
}

.gt-stat-item {
  text-align: center;
  padding: 8px 4px;
}

.gt-stat-item label {
  display: block;
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
}

.gt-value {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.gt-value.positive {
  color: #e65d5d;
}

.gt-value.negative {
  color: #67c23a;
}

.gt-value.gt-warn {
  color: #e65d5d;
}

.gt-fund-list {
  border-top: 1px solid #ebeef5;
  padding-top: 8px;
}

.gt-fund-row {
  padding: 6px 0;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  border-bottom: 1px solid #f5f5f5;
}

.gt-fund-row:last-child {
  border-bottom: none;
}

.gt-fund-name {
  color: #909399;
  font-size: 12px;
}

.gt-fund-data {
  color: #606266;
  margin-left: auto;
}

/* Debate Verdict */
.issues-list {
  padding: 4px 0;
}

.issue-item {
  padding: 6px 0;
  font-size: 13px;
  color: #606266;
}

.issue-fix {
  margin: 2px 0 0 20px;
  color: #409eff;
  font-size: 12px;
}

.arbiter-rationale {
  margin-top: 8px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  color: #606266;
}

/* RFC-012 回测命中率 */
.backtest-grid {
  display: flex;
  gap: 16px;
  margin-bottom: 10px;
}
.backtest-cell {
  flex: 1;
  text-align: center;
  padding: 8px 4px;
  background: #fafbfc;
  border-radius: 6px;
}
.bt-num {
  font-size: 20px;
  font-weight: 700;
  color: #303133;
}
.bt-num.bt-good { color: #67c23a; }
.bt-num.bt-bad { color: #e65d5d; }
.bt-label {
  font-size: 11px;
  color: #909399;
  margin-top: 4px;
}
.by-action { margin-bottom: 10px; }
.bt-hint { margin-top: 4px; }
.bt-empty {
  color: #909399;
  font-size: 13px;
  line-height: 1.6;
}
</style>
