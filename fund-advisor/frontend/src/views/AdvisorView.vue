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
                    <span class="suggestion-text" v-if="h.suggestion">{{ actionLabel(h.suggestion) }}</span>
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
                      <span class="action-badge">{{ actionLabel(a.action) }}</span>
                      <el-tag v-if="a.priority === 'high'" type="danger" size="small">高优</el-tag>
                      <el-tag v-else-if="a.priority === 'medium'" type="warning" size="small">中</el-tag>
                    </div>
                    <p class="action-reason">{{ cleanEvidence(a.reason) }}</p>
                  </div>
                </el-timeline-item>
              </el-timeline>
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
import { ref, onMounted } from 'vue'
import { Promotion, List, Warning, DataAnalysis, Tickets, WarnTriangleFilled, CircleCheckFilled, Histogram } from '@element-plus/icons-vue'
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
const HISTORY_LIMIT = 20

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

function actionLabel(action) {
  const labels = {
    add: '加仓',
    increase: '增持',
    reduce: '减仓',
    decrease: '减持',
    hold: '持有',
    watch: '关注',
  }
  return labels[action] || action
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
    // Refresh history
    await loadHistory()
  } catch (e) {
    error.value = '分析请求失败: ' + e.message
    ElMessage.error('分析失败')
  } finally {
    loading.value = false
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

onMounted(async () => {
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
</style>
