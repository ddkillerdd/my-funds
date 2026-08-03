<template>
  <div class="plan-wizard">
    <el-tabs v-model="activeTab" type="card">
      <!-- ───────────── 向导: 新建方案 ───────────── -->
      <el-tab-pane label="新建方案" name="wizard">
        <el-steps :active="step" align-center finish-status="success" class="wizard-steps">
          <el-step title="预算与风险" />
          <el-step title="AI 荐基" />
          <el-step title="智能配比" />
          <el-step title="回测验证" />
          <el-step title="分批计划" />
          <el-step title="确认建仓" />
        </el-steps>

        <!-- Step 1: 预算与风险 -->
        <el-card v-if="step === 1" shadow="never" class="tool-card">
          <el-form label-width="120px" @submit.prevent>
            <el-form-item label="固定预算(元)">
              <el-input-number v-model="budget" :min="100" :max="1000000" :step="100" />
            </el-form-item>
            <el-form-item label="风险偏好">
              <el-radio-group v-model="riskProfile">
                <el-radio-button value="conservative">保守</el-radio-button>
                <el-radio-button value="balanced">稳健</el-radio-button>
                <el-radio-button value="aggressive">进取</el-radio-button>
              </el-radio-group>
              <div class="risk-desc">{{ riskDesc }}</div>
            </el-form-item>
            <el-form-item label="基金类型(可选)">
              <el-select v-model="fundTypes" multiple clearable placeholder="不限类型" style="width: 360px">
                <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="recommending" @click="runRecommend">
                {{ recommending ? 'AI 研判中(约1-2分钟)...' : '开始 AI 荐基' }}
              </el-button>
              <el-button v-if="recError" type="danger" text @click="recError = ''">清除错误</el-button>
            </el-form-item>
          </el-form>
          <div v-if="recError" class="error-box">{{ recError }}</div>

          <div v-if="recResult" class="section-block">
            <el-alert
              v-if="recResult.fallback_used"
              type="warning" :closable="false"
              title="AI 研判暂不可用，已回退到量化规则结果"
            />
            <div class="section-title">推荐基金 Top {{ recResult.picks?.length }} <el-tag size="small" type="info">{{ recResult.model || '规则' }}</el-tag></div>
            <el-table :data="recResult.picks || []" stripe class="rec-table">
              <el-table-column label="基金代码" prop="fund_code" width="110" />
              <el-table-column label="基金名称" prop="fund_name" min-width="200" />
              <el-table-column label="类型" prop="fund_type" width="90" />
              <el-table-column label="评分" width="80">
                <template #default="{ row }">
                  <el-tag :type="scoreTag(row.total_score)">{{ row.total_score }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="建议配比" width="100">
                <template #default="{ row }">
                  <b>{{ row.suggested_ratio_pct }}%</b>
                </template>
              </el-table-column>
              <el-table-column label="择时" width="140">
                <template #default="{ row }">
                  <el-tag size="small" :type="windowTag(row.timing_window)">{{ windowText(row.timing_window) }}</el-tag>
                  <div v-if="row.timing_score != null" class="timing-score">信号 {{ row.timing_score }}</div>
                </template>
              </el-table-column>
              <el-table-column label="AI 理由" prop="reason" min-width="220" />
              <el-table-column width="60" align="center">
                <template #default="{ row }">
                  <el-checkbox v-model="selectedCodes[row.fund_code]" />
                </template>
              </el-table-column>
            </el-table>
            <el-alert v-if="recResult.overall_view" type="info" :closable="false" class="overall-box">
              <template #title>综合研判</template>
              {{ recResult.overall_view }}
            </el-alert>
            <div class="step-actions">
              <el-button type="primary" @click="toAllocate">下一步：智能配比</el-button>
            </div>
          </div>
        </el-card>

        <!-- Step 3: 配比 -->
        <el-card v-if="step === 3" shadow="never" class="tool-card">
          <div class="section-title">智能配比（风控约束：单只 ≤25%、≥5%、权重和=100%）</div>
          <el-table :data="allocRows" stripe>
            <el-table-column label="基金代码" prop="fund_code" width="110" />
            <el-table-column label="基金名称" prop="fund_name" min-width="200" />
            <el-table-column label="类型" prop="fund_type" width="90" />
            <el-table-column label="建议配比" width="120">
              <template #default="{ row }">
                <el-input-number v-model="allocInputs[row.fund_code]" :min="5" :max="25" :step="1" size="small" />
                <span>%</span>
              </template>
            </el-table-column>
            <el-table-column label="约束状态" width="120">
              <template #default="{ row }">
                <el-tag :type="allocOk(row) ? 'success' : 'danger'" size="small">
                  {{ allocOk(row) ? '合规' : '超限' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div class="sum-line">权重合计：<b :class="sumClass">{{ allocSum.toFixed(2) }}%</b>（应为 100%）</div>
          <div v-if="allocError" class="error-box">{{ allocError }}</div>
          <div class="step-actions">
            <el-button @click="allocMode = 'auto'">重新自动配比</el-button>
            <el-button type="primary" @click="nextAlloc">下一步：回测验证</el-button>
          </div>
        </el-card>

        <!-- Step 4: 回测验证 -->
        <el-card v-if="step === 4" shadow="never" class="tool-card">
          <div class="section-title">回测验证（每日再平衡信号，含回撤修复诊断）</div>
          <el-form inline @submit.prevent>
            <el-form-item label="回测窗口">
              <el-checkbox-group v-model="btWindows">
                <el-checkbox value="30">30天</el-checkbox>
                <el-checkbox value="90">90天</el-checkbox>
                <el-checkbox value="365">365天</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="btLoading" @click="runBacktest">
                {{ btLoading ? '回测中...' : '开始回测' }}
              </el-button>
            </el-form-item>
          </el-form>
          <div v-if="btError" class="error-box">{{ btError }}</div>

          <div v-if="btResult" class="section-block">
            <el-row :gutter="16">
              <el-col :span="8" v-for="(w, wd) in btResult.windows" :key="wd">
                <el-card shadow="hover" class="bt-card">
                  <div class="bt-window-title">{{ wd }} 天窗口</div>
                  <div class="metric-row"><span>策略收益</span><b :class="pos(w.strategy_return_pct)">{{ w.strategy_return_pct }}%</b></div>
                  <div class="metric-row"><span>超额收益</span><b :class="pos(w.excess_return_pct)">{{ w.excess_return_pct }}%</b></div>
                  <div class="metric-row"><span>最大回撤</span><b class="neg">{{ w.strategy_max_drawdown_pct }}%</b></div>
                  <div class="metric-row"><span>回撤修复</span>
                    <b>{{ w.max_drawdown_recovery_days }} 天（{{ w.recovery_status }}）</b>
                  </div>
                  <div class="metric-row"><span>盈利概率</span><b>{{ w.win_rate_pct }}%</b></div>
                </el-card>
              </el-col>
            </el-row>
            <el-alert v-if="btResult.summary" type="success" :closable="false" class="overall-box">
              <template #title>回测结论：{{ btResult.summary.verdict }}</template>
              {{ btResult.summary.detail }}
            </el-alert>
            <ul v-if="btResult.advice && btResult.advice.length" class="advice-list">
              <li v-for="(a, i) in btResult.advice" :key="i">💡 {{ a }}</li>
            </ul>
            <div class="step-actions">
              <el-button @click="step = 3">上一步</el-button>
              <el-button type="primary" @click="nextTranche">下一步：分批计划</el-button>
            </div>
          </div>
        </el-card>

        <!-- Step 5: 分批计划 -->
        <el-card v-if="step === 5" shadow="never" class="tool-card">
          <div class="section-title">分批计划（DCA 倍率 0.6/1.0/1.3 × 择时档位）</div>
          <el-form inline @submit.prevent>
            <el-form-item label="总周数">
              <el-input-number v-model="totalWeeks" :min="4" :max="104" :step="4" />
            </el-form-item>
            <el-form-item label="间隔(周)">
              <el-input-number v-model="intervalWeeks" :min="1" :max="8" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="trancheLoading" @click="generateTranches">
                {{ trancheLoading ? '生成中...' : '生成分批' }}
              </el-button>
            </el-form-item>
          </el-form>
          <div v-if="trancheError" class="error-box">{{ trancheError }}</div>

          <div v-if="tranches.length" class="section-block">
            <el-table :data="tranches" stripe size="small" max-height="340">
              <el-table-column label="批次" prop="tranche_no" width="70" />
              <el-table-column label="金额(元)" prop="amount" width="100" />
              <el-table-column label="份额" prop="units" width="110" />
              <el-table-column label="择时" prop="window" width="100" />
              <el-table-column label="DCA倍率" width="90">
                <template #default="{ row }"><el-tag size="small">{{ row.dca_multiplier }}</el-tag></template>
              </el-table-column>
              <el-table-column label="计划日期" prop="plan_date" width="120" />
              <el-table-column label="状态" prop="status" width="100" />
            </el-table>
            <div class="sum-line">共 {{ tranches.length }} 批，合计约 <b>{{ trancheTotal.toFixed(2) }} 元</b> / 预算 {{ budget }} 元</div>
            <div class="step-actions">
              <el-button @click="step = 4">上一步</el-button>
              <el-button type="primary" @click="nextConfirm">下一步：确认建仓</el-button>
            </div>
          </div>
        </el-card>

        <!-- Step 6: 确认建仓 -->
        <el-card v-if="step === 6" shadow="never" class="tool-card">
          <div class="section-title">确认建仓</div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="方案名称">{{ planName }}</el-descriptions-item>
            <el-descriptions-item label="预算"><b>{{ budget }} 元</b></el-descriptions-item>
            <el-descriptions-item label="风险偏好">{{ riskProfile }}</el-descriptions-item>
            <el-descriptions-item label="基金数">{{ allocRows.length }} 只</el-descriptions-item>
          </el-descriptions>
          <el-alert type="info" :closable="false" class="overall-box">
            <template #title>分批计划已生成</template>
            首期将立即执行 {{ defaultExecute }} 批，其余按计划日期分批定投。
          </el-alert>
          <el-form inline class="mt-16" @submit.prevent>
            <el-form-item label="首期执行批次">
              <el-input-number v-model="executeTranches" :min="1" :max="tranches.length || 1" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="large" :loading="confirmLoading" @click="confirmEntry">
                {{ confirmLoading ? '建仓中...' : '✅ 确认建仓' }}
              </el-button>
            </el-form-item>
          </el-form>
          <div v-if="confirmResult" class="success-box">
            <el-result icon="success" title="建仓成功" sub-title="方案已启用并按批次分批执行">
              <template #extra>
                <el-descriptions :column="4" border size="small">
                  <el-descriptions-item label="状态">{{ confirmResult.status }}</el-descriptions-item>
                  <el-descriptions-item label="已投入">{{ confirmResult.used_amount }} 元</el-descriptions-item>
                  <el-descriptions-item label="剩余">{{ confirmResult.remaining }} 元</el-descriptions-item>
                  <el-descriptions-item label="已执行批次">{{ confirmResult.executed?.length }}</el-descriptions-item>
                </el-descriptions>
                <el-button class="mt-16" @click="resetWizard">再建一个方案</el-button>
              </template>
            </el-result>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ───────────── 我的方案列表 ───────────── -->
      <el-tab-pane label="我的方案" name="list">
        <el-button class="mb-16" type="primary" plain size="small" :loading="plansLoading" @click="loadPlans">
          刷新
        </el-button>
        <el-table :data="plans" stripe>
          <el-table-column label="ID" prop="id" width="60" />
          <el-table-column label="方案名称" prop="name" min-width="180" />
          <el-table-column label="预算" width="100">
            <template #default="{ row }"><b>{{ row.total_budget }}</b> 元</template>
          </el-table-column>
          <el-table-column label="已投入" width="100">
            <template #default="{ row }">{{ row.used_amount }} 元</template>
          </el-table-column>
          <el-table-column label="剩余" width="100">
            <template #default="{ row }">{{ row.remaining }} 元</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusTag(row.status)">{{ statusTagText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="风险" prop="risk_profile" width="90" />
          <el-table-column label="创建时间" prop="created_at" width="160" />
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="viewPlanDetail(row.id)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!plansLoading && !plans.length" description="还没有投资方案" />
      </el-tab-pane>
    </el-tabs>

    <!-- 计划详情抽屉 -->
    <el-drawer v-model="drawerVisible" title="方案详情" size="480px">
      <template v-if="planDetail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="名称">{{ planDetail.name }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ planDetail.status }}</el-descriptions-item>
          <el-descriptions-item label="预算">{{ planDetail.total_budget }}</el-descriptions-item>
          <el-descriptions-item label="剩余">{{ planDetail.remaining }}</el-descriptions-item>
        </el-descriptions>
        <h4 class="drawer-sub">分批批次</h4>
        <el-table :data="planDetail.tranches || []" size="small" max-height="260" stripe>
          <el-table-column label="批" prop="tranche_no" width="50" />
          <el-table-column label="金额" prop="amount" width="90" />
          <el-table-column label="日期" prop="plan_date" width="110" />
          <el-table-column label="状态" prop="status" width="90" />
        </el-table>
        <h4 class="drawer-sub">计划持仓（独立核算）</h4>
        <el-table :data="planDetail.holdings || []" size="small" max-height="200" stripe>
          <el-table-column label="代码" prop="fund_code" width="90" />
          <el-table-column label="成本" prop="total_cost" width="80" />
          <el-table-column label="份额" prop="total_units" width="90" />
          <el-table-column label="现值/单位" prop="last_nav" width="90" />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  recommendPlan, allocatePlan, generatePlanTranches, confirmPlanEntry,
  submitPlanBacktest, getPlanBacktestTask, createPlan, listPlans, getPlanDetail,
} from '../api'

const activeTab = ref('wizard')
const step = ref(1)

// Step1
const budget = ref(1000)
const riskProfile = ref('balanced')
const fundTypes = ref([])
const typeOptions = ['股票', '混合', '债券', '指数', 'QDII', '货币']
const recommending = ref(false)
const recError = ref('')
const recResult = ref(null)
const selectedCodes = reactive({})
const riskDescMap = {
  conservative: '偏债防守，高波基金份额下调',
  balanced: '均衡配置，标准权重',
  aggressive: '偏股进攻，高波基金份额上调',
}
const riskDesc = computed(() => riskDescMap[riskProfile.value])

// Step3 配比
const allocRows = ref([])
const allocInputs = reactive({})
const allocError = ref('')
const allocMode = ref('auto')

// Step4 回测
const btWindows = ref(['90', '365'])
const btLoading = ref(false)
const btError = ref('')
const btResult = ref(null)
let btTimer = null

// Step5 分批
const totalWeeks = ref(16)
const intervalWeeks = ref(2)
const trancheLoading = ref(false)
const trancheError = ref('')
const tranches = ref([])

// Step6
const planName = ref('我的入场计划')
const executeTranches = ref(1)
const confirmLoading = ref(false)
const confirmResult = ref(null)

// 列表
const plans = ref([])
const plansLoading = ref(false)
const planDetail = ref(null)
const drawerVisible = ref(false)
const activePlanId = ref(null)

const defaultExecute = computed(() => Math.min(1, tranches.value.length || 1))
const allocSum = computed(() => Object.values(allocInputs).reduce((s, v) => s + (Number(v) || 0), 0))
const sumClass = computed(() => (Math.abs(allocSum.value - 100) < 1 ? 'ok' : 'bad'))

function scoreTag(s) { return s >= 75 ? 'danger' : s >= 65 ? 'warning' : 'info' }
function windowTag(w) { return w === 'now_entry' ? 'success' : w === 'staged_entry' ? 'warning' : w === 'avoid' ? 'danger' : 'info' }
function windowText(w) {
  return w === 'now_entry' ? '适合买入' : w === 'staged_entry' ? '分批买入' : w === 'avoid' ? '暂避' : '等待' 
}
function statusTag(s) { return s === 'active' ? 'success' : s === 'completed' ? 'info' : 'warning' }
function statusTagText(s) { return s === 'active' ? '进行中' : s === 'completed' ? '已完成' : '草稿' }
function pos(v) { return v >= 0 ? 'ok' : 'neg' }
function allocOk(row) {
  const v = Number(allocInputs[row.fund_code]) || 0
  return v >= 5 && v <= 25
}

async function runRecommend() {
  recError.value = ''
  recResult.value = null
  recommending.value = true
  // 空响应时自动重试(偶发 proxy/长请求空 body, 快路径已验证稳定成功)
  const maxRetry = 2
  let body = null
  for (let attempt = 0; attempt <= maxRetry; attempt++) {
    try {
      // 注意: api 实例响应拦截器已 unwrap => recommendPlan 直接返回 data(非 {data})
      const res = await recommendPlan({
        budget: budget.value,
        risk_profile: riskProfile.value,
        fund_types: fundTypes.value.length ? fundTypes.value : null,
      })
      const b = res ?? {}
      const picks = Array.isArray(b.picks) ? b.picks : []
      const isEmptyResp = typeof b === 'object' && b !== null && Object.keys(b).length === 0
      // 拿到有效结果(有picks 或 明确业务报错), 直接采用
      if (picks.length || (b?.detail || b?.error)) { body = b; break }
      // 空响应且非最后尝试 -> 重试
      if (isEmptyResp && attempt < maxRetry) {
        await new Promise(r => setTimeout(r, 1500))
        continue
      }
      body = b
      break
    } catch (e) {
      // 网络异常: 非最后尝试则重试
      if (attempt < maxRetry) { await new Promise(r => setTimeout(r, 1500)); continue }
      recError.value = e?.response?.data?.detail || e.message || '荐基失败'
      recommending.value = false
      return
    }
  }
  const picks = Array.isArray(body?.picks) ? body.picks : []
  if (!picks.length) {
    recError.value = body?.detail || body?.error
      ? (body.detail || body.error)
      : '荐基服务响应异常(可能超时或服务重启)，请稍后重试'
    recommending.value = false
    return
  }
  recResult.value = body
  Object.keys(selectedCodes).forEach((k) => delete selectedCodes[k])
  picks.forEach((p) => { selectedCodes[p.fund_code] = true })
  recommending.value = false
}

function toAllocate() {
  const recPicks = recResult.value?.picks || []
  const selected = Object.entries(selectedCodes)
    .filter(([, v]) => v)
    .map(([code]) => recPicks.find((p) => p.fund_code === code))
    .filter(Boolean)
  if (selected.length < 1) { ElMessage.warning('请至少勾选 1 只基金'); return }
  execAllocate(selected)
}

async function execAllocate(picks) {
  allocError.value = ''
  allocMode.value = 'auto'
  try {
    const res = await allocatePlan({ picks, risk_profile: riskProfile.value })
    allocRows.value = res.data.rows || res.data.weights ? toAllocRows(picks, res.data) : []
    Object.keys(allocInputs).forEach((k) => delete allocInputs[k])
    allocRows.value.forEach((r) => { allocInputs[r.fund_code] = r.allocation_pct })
    step.value = 3
  } catch (e) {
    allocError.value = e?.response?.data?.detail || e.message || '配比失败'
  }
}

function toAllocRows(picks, data) {
  const weights = data.weights || {}
  const itemMap = {};
  (data.items || []).forEach((it) => { itemMap[it.fund_code] = it.weight_pct })
  return picks.map((p) => ({
    fund_code: p.fund_code,
    fund_name: p.fund_name,
    fund_type: p.fund_type,
    allocation_pct: weights[p.fund_code] ?? itemMap[p.fund_code] ?? 0,
  }))
}

function nextAlloc() {
  if (Math.abs(allocSum.value - 100) > 1) {
    ElMessage.warning('权重需合计 100%（或点击重新自动配比归零后手动填）')
    return
  }
  // 修正为 sum=100 (手动输入可能因四舍五入差)
  const data = allocRows.value.map((r) => ({
    fund_code: r.fund_code,
    fund_name: r.fund_name,
    fund_type: r.fund_type,
    suggested_ratio_pct: Number(allocInputs[r.fund_code]) || 0,
  }))
  execBacktestPrepare(data)
}

async function execBacktestPrepare(data) {
  btResult.value = null
  btError.value = ''
  step.value = 4
  const amounts = {}
  let rem = budget.value
  data.forEach((r) => {
    if (r === data[data.length - 1]) { amounts[r.fund_code] = Math.round(rem); return }
    const a = Math.round(budget.value * r.suggested_ratio_pct / 100)
    amounts[r.fund_code] = a
    rem -= a
  })
  const funds = data.map((r) => ({
    fund_code: r.fund_code,
    fund_name: r.fund_name,
    amount: amounts[r.fund_code],
  }))
  window.__pendingPlanFunds = { data, funds }
}

async function runBacktest() {
  const c = window.__pendingPlanFunds
  if (!c) { ElMessage.warning('请先完成配比'); return }
  const windows = btWindows.value.map(Number)
  btLoading.value = true
  btError.value = ''
  try {
    const tx = await submitPlanBacktest({ funds: c.funds, windows })
    pollBt(tx.data.task_id)
  } catch (e) {
    btError.value = e?.response?.data?.detail || e.message
    btLoading.value = false
  }
}

function pollBt(taskId) {
  clearInterval(btTimer)
  btTimer = setInterval(async () => {
    try {
      const res = await getPlanBacktestTask(taskId)
      if (res.data.status === 'running') return
      clearInterval(btTimer)
      btLoading.value = false
      if (res.data.status === 'done') btResult.value = res.data.result
      else btError.value = res.data.error || '回测失败'
    } catch (e) {
      clearInterval(btTimer)
      btLoading.value = false
      btError.value = e.message
    }
  }, 3000)
}

function nextTranche() { step.value = 5 }

async function generateTranches() {
  const c = window.__pendingPlanFunds
  trancheError.value = ''
  trancheLoading.value = true
  try {
    // 先创建方案
    const alloc = {}
    c.data.forEach((r) => { alloc[r.fund_code] = r.suggested_ratio_pct })
    const planRes = await createPlan({
      total_budget: budget.value,
      risk_profile: riskProfile.value,
      name: planName.value,
      target_allocation: alloc,
      ai_summary: recResult.value?.overall_view || null,
    })
    const planId = planRes.data.id
    // 分批择时交给后端引擎自动判断(实时择时信号), 不手动指定
    const fund_windows = {}
    const trRes = await generatePlanTranches(planId, {
      fund_windows,
      total_weeks: totalWeeks.value,
      interval_weeks: intervalWeeks.value,
    })
    tranches.value = Array.isArray(trRes.data) ? trRes.data : trRes.data?.tranches || []
    activePlanId.value = planId
    executeTranches.value = 1
  } catch (e) {
    trancheError.value = e?.response?.data?.detail || e.message
  } finally {
    trancheLoading.value = false
  }
}

const trancheTotal = computed(() => tranches.value.reduce((s, t) => s + (Number(t.amount) || 0), 0))

function nextConfirm() {
  if (!activePlanId.value) { ElMessage.warning('请先生成分批计划'); return }
  step.value = 6
}

async function confirmEntry() {
  if (!activePlanId.value) { ElMessage.warning('请先生成分批计划'); return }
  confirmLoading.value = true
  try {
    const res = await confirmPlanEntry(activePlanId.value, { execute_tranches: executeTranches.value })
    confirmResult.value = res.data
    ElMessage.success('建仓成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  } finally {
    confirmLoading.value = false
  }
}

function resetWizard() {
  step.value = 1
  recResult.value = null
  btResult.value = null
  tranches.value = []
  confirmResult.value = null
  activePlanId.value = null
  window.__pendingPlanFunds = null
}

async function loadPlans() {
  plansLoading.value = true
  try {
    const res = await listPlans()
    plans.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    plansLoading.value = false
  }
}

async function viewPlanDetail(id) {
  try {
    const res = await getPlanDetail(id)
    planDetail.value = res.data
    drawerVisible.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(() => loadPlans())
</script>

<style scoped>
.page-header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.tip-text { color: #909399; font-size: 13px; }
.wizard-steps { margin-bottom: 20px; }
.tool-card { margin-bottom: 16px; }
.error-box { background: #fef0f0; color: #f56c6c; padding: 10px 14px; border-radius: 4px; margin: 10px 0; }
.section-block { margin-top: 18px; }
.section-title { font-weight: 600; margin: 12px 0; }
.rec-table { margin-bottom: 12px; }
.timing-score { font-size: 12px; color: #909399; line-height: 1.4; }
.overall-box { margin-top: 12px; white-space: pre-wrap; }
.step-actions { margin-top: 18px; display: flex; gap: 12px; align-items: center; }
.sum-line { margin: 12px 0; }
.ok { color: #67c23a; }
.bad { color: #f56c6c; }
.neg { color: #f56c6c; font-weight: 600; }
.risk-desc { color: #909399; font-size: 12px; line-height: 32px; }
.bt-card { padding: 6px; }
.bt-window-title { font-weight: 700; margin-bottom: 10px; text-align: center; }
.metric-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px dashed #eee; font-size: 13px; }
.metric-row span { color: #909399; }
.advice-list { margin-top: 10px; color: #606266; font-size: 13px; line-height: 1.8; }
.drawer-sub { margin: 16px 0 8px; }
.mt-16 { margin-top: 16px; }
.mb-16 { margin-bottom: 12px; }
</style>
