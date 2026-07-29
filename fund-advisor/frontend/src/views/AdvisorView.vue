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
            <span v-if="lastGenerated" class="last-gen">
              上次分析: {{ lastGenerated }}
            </span>
          </div>
        </el-col>
        <el-col :span="12" style="text-align: right">
          <el-button type="primary" :icon="Promotion" :loading="loading" @click="runAnalysis">
            {{ loading ? '分析中...' : '生成分析报告' }}
          </el-button>
        </el-col>
      </el-row>
    </el-card>

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
                <span class="concern-text" v-if="h.concerns">{{ h.concerns }}</span>
              </el-col>
              <el-col :span="6">
                <span class="suggestion-text" v-if="h.suggestion">{{ h.suggestion }}</span>
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
                <p class="action-reason">{{ a.reason }}</p>
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
        </el-descriptions>
      </el-card>

      <!-- Footer -->
      <div class="report-footer">
        报告生成于 {{ report.generated_at }} | 模型: {{ report.model }}
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Promotion, List, Warning, DataAnalysis } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const report = ref(null)
const error = ref('')
const apiConfigured = ref(false)
const lastGenerated = ref('')

function healthColor(score) {
  if (score >= 70) return '#67c23a'
  if (score >= 40) return '#e6a23c'
  return '#f56c6c'
}

function actionType(action) {
  if (action === 'add') return 'primary'
  if (action === 'reduce') return 'danger'
  if (action === 'watch') return 'warning'
  return 'info'
}

function actionLabel(action) {
  const labels = {
    add: '加仓',
    reduce: '减仓',
    hold: '持有',
    watch: '关注',
  }
  return labels[action] || action
}

async function runAnalysis() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/advisor/analyze', { method: 'POST' })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    report.value = data
    lastGenerated.value = data.generated_at
    ElMessage.success('分析完成')
  } catch (e) {
    error.value = '分析请求失败: ' + e.message
    ElMessage.error('分析失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
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
  color: #909399;
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
</style>
