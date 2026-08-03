<template>
  <div class="recommend-view">
    <h2 class="page-title">荐基 &amp; 择时</h2>

    <el-tabs v-model="activeTab" type="card">
      <!-- ─────────────────----- 入场择时 ─────────────────----- -->
      <el-tab-pane label="入场择时" name="timing">
        <el-card shadow="never" class="tool-card">
          <el-form :inline="true" @submit.prevent>
            <el-form-item label="基金代码">
              <el-input
                v-model="timingCode"
                placeholder="如 161725"
                style="width: 160px"
                clearable
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="timingLoading" @click="runTiming">
                {{ timingLoading ? '分析中...' : '查询择时' }}
              </el-button>
            </el-form-item>
            <el-form-item>
              <span class="tip-text">纯量化判断，不依赖 AI 模型；仅供参考，不构成投资建议</span>
            </el-form-item>
          </el-form>

          <div v-if="timingError" class="error-box">{{ timingError }}</div>

          <el-result
            v-if="timingResult && !timingError"
            :icon="timingResultIcon"
            :title="timingResult.action_label"
            :sub-title="timingResult.fund_name"
          >
            <template #extra>
              <div class="timing-detail">
                <el-row :gutter="16">
                  <el-col :span="8">
                    <div class="metric-card">
                      <div class="metric-label">置信度</div>
                      <div class="metric-value">{{ timingResult.confidence_pct }}%</div>
                    </div>
                  </el-col>
                  <el-col :span="8">
                    <div class="metric-card">
                      <div class="metric-label">风控门</div>
                      <div class="metric-value" :class="gateClass">
                        {{ timingResult.risk_gate_status === 'blocked' ? '已拦截' : '放行' }}
                      </div>
                    </div>
                  </el-col>
                  <el-col :span="8">
                    <div class="metric-card">
                      <div class="metric-label">建议配比(每期)</div>
                      <div class="metric-value">
                        {{ timingResult.suggested_dca ? timingResult.suggested_dca.base_amount_pct + '%' : '--' }}
                      </div>
                    </div>
                  </el-col>
                </el-row>

                <div v-if="timingResult.risk_gate_reason" class="gate-reason">
                  风控说明：{{ timingResult.risk_gate_reason }}
                </div>

                <div v-if="timingResult.timing_factors.length" class="factor-list">
                  <div v-for="f in timingResult.timing_factors" :key="f.name" class="factor-row">
                    <span class="factor-name">{{ f.name }}</span>
                    <el-progress
                      :percentage="Math.round(f.score)"
                      :status="factorStatus(f.score)"
                      :stroke-width="14"
                    />
                    <span class="factor-evidence" :title="f.evidence">{{ f.evidence }}</span>
                  </div>
                </div>
              </div>
            </template>
          </el-result>
        </el-card>
      </el-tab-pane>

      <!-- ───────────────────── 荐基打分 ───────────────────── -->
      <el-tab-pane label="荐基打分" name="screen">
        <el-card shadow="never" class="tool-card">
          <div class="screen-input">
            <div class="label">候选基金（每行一个，格式：代码 名称）</div>
            <el-input
              v-model="candidatesText"
              type="textarea"
              :rows="4"
              placeholder="161725 招商中证白酒指数(LOF)A&#10;110022 易方达消费行业股票&#10;005827 易方达蓝筹精选混合"
            />
            <div class="screen-opts">
              <el-checkbox v-model="usePortfolio">以当前持仓为分散化参照</el-checkbox>
              <el-checkbox v-model="withAi">追加 AI 一句话解读</el-checkbox>
              <span class="tip-text">（AI 只解读不评分，避免幻觉）</span>
            </div>
            <div class="screen-action">
              <el-button type="primary" :loading="screenLoading" @click="runScreen">
                {{ screenLoading ? '评分中...' : '开始评分' }}
              </el-button>
            </div>
          </div>

          <el-alert
            v-if="screenResult && screenResult.notes && screenResult.notes.length"
            :title="screenResult.notes.join('；')"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          />

          <el-table
            v-if="screenResult && screenResult.recommendations.length"
            :data="screenResult.recommendations"
            stripe
            style="width: 100%"
          >
            <el-table-column label="排名" width="70" align="center">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column prop="fund_name" label="基金" min-width="180" />
            <el-table-column label="总分" width="90" align="center" sortable>
              <template #default="{ row }">
                <span class="score-badge" :style="{ color: scoreColor(row.total_score) }">
                  {{ row.total_score }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="style_tag" label="风格" width="110" align="center" />
            <el-table-column label="与持仓相关" width="110" align="center">
              <template #default="{ row }">
                {{ row.correlation_with_portfolio != null ? row.correlation_with_portfolio.toFixed(2) : '--' }}
              </template>
            </el-table-column>
            <el-table-column label="建议配比" width="100" align="center">
              <template #default="{ row }">{{ row.suggested_ratio_pct }}%</template>
            </el-table-column>
            <el-table-column label="解读" min-width="200">
              <template #default="{ row }">
                <span class="ai-text">{{ row.ai_explanation || '--' }}</span>
              </template>
            </el-table-column>
          </el-table>

          <el-empty
            v-else-if="screenResult && !screenLoading"
            :description="screenResult.notes && screenResult.notes.length ? screenResult.notes[0] : '暂无结果'"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { getFundTiming, screenFunds } from '../api/index.js'

const activeTab = ref('timing')

// ---- 择时 ----
const timingCode = ref('')
const timingLoading = ref(false)
const timingResult = ref(null)
const timingError = ref('')

const timingResultIcon = computed(() => {
  if (!timingResult.value) return 'info'
  const rec = timingResult.value.recommendation
  if (['buy_now', 'now_entry', 'staged_entry', 'dca'].includes(rec)) return 'success'
  if (rec === 'wait') return 'warning'
  return 'error' // avoid
})

const gateClass = computed(() =>
  timingResult.value && timingResult.value.risk_gate_status === 'blocked' ? 'gate-blocked' : 'gate-pass'
)

function factorStatus(score) {
  if (score >= 60) return 'success'
  if (score >= 40) return 'warning'
  return 'exception'
}

async function runTiming() {
  const code = timingCode.value.trim()
  if (!code) {
    timingError.value = '请输入基金代码'
    return
  }
  timingLoading.value = true
  timingError.value = ''
  try {
    timingResult.value = await getFundTiming({ fund_code: code })
  } catch {
    // interceptor handles
  } finally {
    timingLoading.value = false
  }
}

// ---- 荐基 ----
const candidatesText = ref('')
const screenLoading = ref(false)
const screenResult = ref(null)
const usePortfolio = ref(true)
const withAi = ref(false)

function parseCandidates() {
  const out = []
  for (const line of candidatesText.value.split('\n')) {
    const t = line.trim()
    if (!t) continue
    const m = t.match(/^(\d{6})\s*(.*)$/)
    if (m) {
      out.push({ fund_code: m[1], fund_name: m[2] || m[1] })
    }
  }
  return out
}

function scoreColor(score) {
  if (score >= 60) return '#67c23a'
  if (score >= 40) return '#e6a23c'
  return '#f56c6c'
}

async function runScreen() {
  const candidates = parseCandidates()
  if (!candidates.length) {
    screenResult.value = { recommendations: [], notes: ['请按「代码 名称」格式输入候选基金'] }
    return
  }
  if (candidates.length > 10) {
    screenResult.value = { recommendations: [], notes: ['单次最多 10 只候选，已截断前 10 只'] }
  }
  screenLoading.value = true
  try {
    screenResult.value = await screenFunds({
      candidates: candidates.slice(0, 10),
      top_n: 10,
      use_current_portfolio: usePortfolio.value,
      with_ai_explanation: withAi.value,
    })
  } catch {
    // interceptor handles
  } finally {
    screenLoading.value = false
  }
}
</script>

<style scoped>
.tool-card { margin-bottom: 16px; }
.tip-text { color: #909399; font-size: 12px; margin-left: 8px; }
.error-box {
  color: #f56c6c;
  background: #fef0f0;
  border: 1px solid #fbc4c4;
  border-radius: 4px;
  padding: 12px 16px;
  margin-top: 8px;
}
.timing-detail { width: 100%; }
.metric-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}
.metric-label { color: #909399; font-size: 12px; margin-bottom: 6px; }
.metric-value { font-size: 22px; font-weight: 600; }
.gate-blocked { color: #f56c6c; }
.gate-pass { color: #67c23a; }
.gate-reason {
  margin-top: 12px;
  padding: 8px 12px;
  background: #fdf6ec;
  color: #e6a23c;
  border-radius: 4px;
  font-size: 13px;
}
.factor-list { margin-top: 16px; text-align: left; }
.factor-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.factor-name { width: 80px; color: #606266; font-size: 13px; }
.factor-row .el-progress { flex: 1; }
.factor-evidence {
  width: 260px;
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.screen-input .label { margin-bottom: 8px; color: #606266; font-size: 14px; }
.screen-opts { margin: 12px 0; }
.screen-action { margin-top: 4px; }
.score-badge { font-size: 18px; font-weight: 700; }
.ai-text { font-size: 13px; color: #606266; }
</style>
