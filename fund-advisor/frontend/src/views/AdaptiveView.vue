<template>
  <div class="adaptive-view">
    <h2 class="page-title">自适应优化 · Walk-Forward 参数自学习</h2>
    <el-alert
      title="半自动模式：系统跑出已验证的参数 + 样本外证据作为推荐；只有你点『采纳』才会写入实战报告。未确认或未通过稳健性校验的推荐，一律不影响实盘。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    />

    <!-- 判读对照表: 人话翻译每个数字 -->
    <el-card shadow="never" class="guide-card">
      <template #header>
        <div class="card-header">
          <span>📖 怎么判断该不该采纳？(照着看)</span>
          <el-link type="primary" @click="guideOpen = !guideOpen">{{ guideOpen ? '收起 ▲' : '展开 ▼' }}</el-link>
        </div>
      </template>
      <div v-if="guideOpen" class="guide">
        <p class="guide-head">从上到下看，<b>任何一格不合格就放弃</b>：</p>
        <table class="guide-table">
          <thead>
            <tr><th style="width:110px">看什么</th><th style="width:150px">算什么意思</th><th>怎么算合格 👌</th><th>怎么算放弃 👎</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><b>① 校验：通过/未通过</b></td>
              <td>系统先自己筛过一遍，判断这参数是不是“假的高收益”</td>
              <td class="ok">✓ 通过（绿标）</td>
              <td class="no">✗ 未通过（黄标）→ 直接跳过，别采纳</td>
            </tr>
            <tr>
              <td><b>② 超额 + 相对增益</b></td>
              <td>用新参数比“什么都不改(用默认)”在盲测段多赚多少个百分点</td>
              <td class="ok">增益明显为正，如 +0.30pp 以上</td>
              <td class="no">增益 ≤ 0 → 改了白改甚至更差，否决</td>
            </tr>
            <tr>
              <td><b>③ 回撤</b></td>
              <td>历史上最惨时，这个参数让钱最多跌多少（风险地板）</td>
              <td class="ok">低于上限：中波动 ≤15%、高波动 ≤20~25%</td>
              <td class="no">超过上限 → 风险你扛不起，丢</td>
            </tr>
            <tr>
              <td><b>④ 夏普</b></td>
              <td>这多赚的钱，是划算的赚，还是靠多担风险硬换</td>
              <td class="ok">正数，如 0.30+ → 划算，采纳</td>
              <td class="no">负的很明显（如 -0.5）→ 性价比差，别碰</td>
            </tr>
          </tbody>
        </table>
        <p class="guide-tip">💡 心法：<b>通过 + 增益正 + 回撤没超上限 + 夏普不是负的 → 才点采纳；缺任一就否决。</b><br/>
        左下“**当前实战生效**”是你现在实际用的参数；采纳后从下次报告起生效，随时可一键回退保守默认。</p>
      </div>
    </el-card>

    <!-- 发起优化 -->
    <el-card shadow="never" class="option-card">
      <div class="fetch-row">
        <span class="label">发起一次 WFA 优化：</span>
        <el-select
          v-model="participants"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="选基金(留空=主库全部)"
          style="width: 420px"
        >
          <el-option
            v-for="f in fundOptions"
            :key="f.fund_code"
            :value="f.fund_code"
            :label="`${f.fund_code} ${f.fund_name}`"
          />
        </el-select>
        <el-select v-model="lookback" style="width: 200px" class="lookback-sel">
          <el-option :value="400" label="回看 400 交易日" />
          <el-option :value="600" label="回看 600 交易日(推荐)" />
          <el-option :value="850" label="回看 850 交易日" />
          <el-option :value="1200" label="回看 1200 交易日" />
        </el-select>
        <el-button type="primary" :loading="running" @click="startOptimize">
          {{ running ? '优化中...' : '开始优化' }}
        </el-button>
      </div>

      <div v-if="running" style="margin-top: 12px">
        <el-progress :percentage="taskProgress" :stroke-width="14" striped />
        <div class="task-progress-text">{{ taskProgressText }}</div>
      </div>
    </el-card>

    <!-- 当前生效参数 -->
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div class="card-header">
          <span>当前实战生效参数（分析师报告采用）</span>
          <el-button
            v-if="overrides.length"
            type="danger"
            plain
            size="small"
            @click="resetOverride"
          >全部回退保守默认</el-button>
        </div>
      </template>
      <el-empty v-if="!overrides.length" description="暂无自定义生效参数，各基金使用对应风险类别的保守默认" :image-size="60" />
      <el-table v-else :data="overrides" size="small">
        <el-table-column prop="risk_class" label="风险类别" width="120">
          <template #default="{ row }">
            <el-tag :type="riskTagType(row.risk_class)">{{ riskLabel(row.risk_class) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="target_vol" label="target_vol" width="120" />
        <el-table-column prop="friction_band_pp" label="friction" width="120" />
        <el-table-column prop="source" label="来源" width="110" />
        <el-table-column prop="note" label="备注" />
      </el-table>
    </el-card>

    <!-- 推荐列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>历史推荐</span>
          <div>
            <el-radio-group v-model="statusFilter" size="small" @change="loadProposals">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="pending">待确认</el-radio-button>
              <el-radio-button value="approved">已采纳</el-radio-button>
              <el-radio-button value="rejected">已否决</el-radio-button>
            </el-radio-group>
          </div>
        </div>
      </template>

      <el-empty v-if="!proposals.length" description="还没有推荐，点击上方『开始优化』" :image-size="80" />
      <el-table v-else :data="proposals" size="small" style="width: 100%">
        <el-table-column label="风险类别" width="110">
          <template #default="{ row }">
            <el-tag :type="riskTagType(row.risk_class)">{{ riskLabel(row.risk_class) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="推荐参数" width="150">
          <template #default="{ row }">
            <span :class="{ 'rec-dim': !row.passed }">
              vol={{ row.target_vol }} / fr={{ row.friction_band_pp }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="保守默认" width="130">
          <template #default="{ row }">
            vol={{ row.default_target_vol }} / fr={{ row.default_friction_band_pp }}
          </template>
        </el-table-column>
        <el-table-column label="样本外证据">
          <template #default="{ row }">
            <div class="evid">
              <span>超额 <b>{{ fmtSign(row.avg_test_excess_pct) }}%</b></span>
              <span>回撤 <b>{{ (row.best_max_drawdown * 100).toFixed(1) }}%</b></span>
              <span>夏普 <b>{{ (row.best_wfe || 0).toFixed(2) }}</b></span>
              <span class="evid-days">(训练{{ row.train_days }} / 测试{{ row.test_days }}天)</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="校验" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.passed" type="success" size="small">✓ 通过</el-tag>
            <el-tooltip v-else :content="(row.reasons || []).join('；')">
              <el-tag type="warning" size="small">未通过</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button
                type="success"
                size="small"
                :disabled="!row.passed"
                @click="doApprove(row)"
              >采纳</el-button>
              <el-button type="warning" size="small" plain @click="doReject(row)">否决</el-button>
            </template>
            <span v-else-if="row.status === 'approved'" class="op-muted">已生效</span>
            <span v-else class="op-muted">已否决</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getSimulatorFunds,
  runAdaptiveOptimize,
  getAdaptiveTask,
  getAdaptiveProposals,
  approveAdaptiveProposal,
  rejectAdaptiveProposal,
  getAdaptiveOverrides,
  resetAdaptiveOverride,
} from '../api'

const fundOptions = ref([])
const participants = ref([])
const lookback = ref(600)

const overrides = ref([])
const proposals = ref([])
const statusFilter = ref('')

// 异步任务轮询
const running = ref(false)
const taskProgress = ref(0)
const taskProgressText = ref('')
const guideOpen = ref(true)

async function loadFunds() {
  try {
    const resp = await getSimulatorFunds()
    fundOptions.value = resp || []
  } catch (e) {
    console.error('load funds failed', e)
  }
}

async function loadOverrides() {
  try {
    const resp = await getAdaptiveOverrides()
    overrides.value = resp || []
  } catch (e) {
    console.error('load overrides failed', e)
  }
}

async function loadProposals() {
  try {
    const resp = await getAdaptiveProposals(statusFilter.value || undefined)
    proposals.value = resp || []
  } catch (e) {
    console.error('load proposals failed', e)
  }
}

async function startOptimize() {
  const params = { lookback_days: lookback.value }
  if (participants.value.length) params.fund_codes = participants.value
  try {
    const resp = await runAdaptiveOptimize(params)
    const taskId = resp.task_id
    if (!taskId) throw new Error('未返回任务ID')
    running.value = true
    taskProgress.value = 5
    taskProgressText.value = '任务已排队...'
    ElMessage.success('优化任务已启动，正在后台计算')
    pollTask(taskId)
  } catch (e) {
    ElMessage.error('发起失败：' + (e?.response?.data?.detail || e.message))
  }
}

function pollTask(taskId) {
  const timer = setInterval(async () => {
    try {
      const resp = await getAdaptiveTask(taskId)
      const st = resp
      if (!st || !st.status) { clearInterval(timer); running.value = false; return }
      taskProgressText.value = st.progress || ''
      taskProgress.value = st.status === 'done' ? 100 : (st.status === 'error' ? -1 : Math.min(90, taskProgress.value + 15))
      if (st.status === 'done') {
        clearInterval(timer)
        running.value = false
        taskProgress.value = 100
        ElMessage.success('优化完成')
        loadProposals()
        loadOverrides()
      } else if (st.status === 'error') {
        clearInterval(timer)
        running.value = false
        taskProgressText.value = '任务失败：' + (st.error || '未知错误')
        ElMessage.error('优化失败：' + (st.error || '未知错误'))
      }
    } catch (e) {
      clearInterval(timer)
      running.value = false
      console.error('poll failed', e)
    }
  }, 3000)
}

async function doApprove(row) {
  try {
    await ElMessageBox.confirm(
      `确认采纳参数 vol=${row.target_vol} / fr=${row.friction_band_pp} 应用于「${riskLabel(row.risk_class)}」类实战报告？`,
      '采纳确认',
      { type: 'warning', confirmButtonText: '确认采纳', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await approveAdaptiveProposal(row.id, '前端采纳')
    ElMessage.success('已采纳并写入实战生效参数')
    loadProposals(); loadOverrides()
  } catch (e) {
    ElMessage.error('采纳失败：' + (e?.response?.data?.detail || e.message))
  }
}

async function doReject(row) {
  try {
    await ElMessageBox.confirm(`确认否决该推荐(proposal#${row.id})？`, '否决', { type: 'info' })
  } catch { return }
  try {
    await rejectAdaptiveProposal(row.id, '前端否决')
    ElMessage.success('已否决')
    loadProposals()
  } catch (e) {
    ElMessage.error('否决失败：' + (e?.response?.data?.detail || e.message))
  }
}

async function resetOverride() {
  try {
    await ElMessageBox.confirm('确认回退所有类别的实战参数到保守默认？', '回退确认', { type: 'warning' })
  } catch { return }
  const resp = await getAdaptiveOverrides()
  const list = resp || []
  for (const o of list) {
    try {
      await resetAdaptiveOverride(o.risk_class)
    } catch (e) { console.error(e) }
  }
  loadOverrides()
}

const fmtSign = (v) => (v > 0 ? '+' : '') + Number(v || 0).toFixed(2)
const riskLabel = (c) => ({ low: '低波动', medium: '中波动', high: '高波动' }[c] || c)
const riskTagType = (c) => ({ low: 'success', medium: 'warning', high: 'danger' }[c] || 'info')
const statusLabel = (s) => ({ pending: '待确认', approved: '已采纳', rejected: '已否决' }[s] || s)
const statusTag = (s) => ({ pending: 'primary', approved: 'success', rejected: 'info' }[s] || 'info')

onMounted(() => {
  loadFunds(); loadProposals(); loadOverrides()
})
</script>

<style scoped>
.adaptive-view { padding: 4px; }
.page-title { margin-top: 0; }
.option-card { margin-bottom: 16px; }
.guide-card { margin-bottom: 16px; }
.guide { font-size: 13px; color: #303133; }
.guide-head { margin: 0 0 8px; }
.guide-table { width: 100%; border-collapse: collapse; }
.guide-table th, .guide-table td { border: 1px solid #e4e7ed; padding: 7px 10px; text-align: left; vertical-align: top; }
.guide-table th { background: #f5f7fa; font-weight: 600; }
.guide-table .ok { color: #67c23a; font-weight: 600; }
.guide-table .no { color: #f56c6c; font-weight: 600; }
.guide-tip { margin-top: 10px; color: #606266; line-height: 1.7; }
.fetch-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.label { color: #606266; font-size: 14px; }
.lookback-sel { margin-left: 4px; }
.task-progress-text { margin-top: 6px; color: #909399; font-size: 12px; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.evid { display: flex; gap: 12px; font-size: 12px; color: #606266; }
.evid b { color: #303133; }
.evid-days { color: #b0b3b8; }
.rec-dim { color: #909399; text-decoration: line-through; }
.op-muted { color: #b0b3b8; font-size: 12px; }
</style>
