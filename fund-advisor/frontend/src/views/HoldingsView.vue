<template>
  <div class="holdings-view">
    <h2 class="page-title">持仓列表</h2>

    <!-- Toolbar -->
    <el-card shadow="never" class="toolbar-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="8">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索基金代码或名称"
            clearable
            :prefix-icon="Search"
            @input="handleSearch"
          />
        </el-col>
        <el-col :span="6">
          <el-select
            v-model="selectedPlatform"
            placeholder="筛选平台"
            clearable
            @change="handlePlatformChange"
          >
            <el-option
              v-for="p in platformOptions"
              :key="p"
              :label="p"
              :value="p"
            />
          </el-select>
        </el-col>
        <el-col :span="10" style="text-align: right">
          <template v-if="holdings.length">
            <span class="summary-text">
              共 {{ holdings.length }} 笔持仓
            </span>
            &nbsp;
            <span class="summary-text text-bold">
              ￥{{ totalMarketValue }}
            </span>
          </template>
          <el-button type="primary" :icon="Plus" @click="goQuickImport" style="margin-left: 12px">
            快捷新增
          </el-button>
          <el-button @click="openCreateDialog">
            精确录入
          </el-button>
          <el-button :icon="Refresh" @click="loadHoldings">
            刷新
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card v-if="groupedHoldings.length" shadow="never" class="summary-card">
      <template #header>
        <div class="card-header">
          <span>按基金汇总</span>
          <span class="summary-hint">同一基金可在多个平台分别持有，分析时按基金合并</span>
        </div>
      </template>
      <el-table :data="groupedHoldings" stripe style="width: 100%" @row-click="handleSummaryRowClick">
        <el-table-column prop="fund_code" label="基金代码" width="110" />
        <el-table-column prop="fund_name" label="基金名称" min-width="190" show-overflow-tooltip />
        <el-table-column label="平台" min-width="180">
          <template #default="{ row }">
            <el-tag v-for="platform in row.platforms" :key="platform" size="small" class="platform-tag">
              {{ platform }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="holding_count" label="持仓笔数" width="90" align="right" />
        <el-table-column label="总份额" width="130" align="right">
          <template #default="{ row }">{{ formatShares(row.total_shares) }}</template>
        </el-table-column>
        <el-table-column label="总市值" width="130" align="right">
          <template #default="{ row }">￥{{ formatNumber(row.total_market_value) }}</template>
        </el-table-column>
        <el-table-column label="总盈亏" width="120" align="right">
          <template #default="{ row }">
            <span :class="pnlClass(row.total_pnl)">
              {{ row.total_pnl != null ? formatNumber(row.total_pnl) : '--' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Holdings Table -->
    <el-card shadow="hover" class="table-card">
      <template #header>
        <div class="card-header">
          <span>各平台持仓明细</span>
          <span class="summary-hint">加减仓只会修改选中的平台账户</span>
        </div>
      </template>
      <el-table
        v-loading="loading"
        :data="pagedHoldings"
        stripe
        style="width: 100%"
        @row-click="handleRowClick"
        default-sort="{ prop: 'current_market_value', order: 'descending' }"
      >
        <el-table-column prop="fund_code" label="基金代码" width="110" />
        <el-table-column prop="fund_name" label="基金名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="120" show-overflow-tooltip />
        <el-table-column prop="fund_account" label="账户别名" width="150" show-overflow-tooltip />
        <el-table-column label="持有份额" width="120" align="right" sortable sort-by="shares">
          <template #default="{ row }">
            {{ formatShares(row.shares) }}
          </template>
        </el-table-column>
        <el-table-column label="最新净值" width="100" align="right">
          <template #default="{ row }">
            {{ row.latest_nav ? Number(row.latest_nav).toFixed(4) : '--' }}
          </template>
        </el-table-column>
        <el-table-column label="成本净值" width="110" align="right">
          <template #default="{ row }">
            <span
              class="editable-cell"
              @click.stop="openCostEdit(row)"
            >
              {{ row.cost_nav ? Number(row.cost_nav).toFixed(4) : '--' }}
              <el-icon class="edit-icon" :size="12"><Edit /></el-icon>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="市值" width="120" align="right" sortable sort-by="current_market_value">
          <template #default="{ row }">
            ￥{{ formatNumber(row.current_market_value || row.market_value) }}
          </template>
        </el-table-column>
        <el-table-column label="总盈亏" width="120" align="right" sortable sort-by="total_pnl">
          <template #default="{ row }">
            <span :class="pnlClass(row.total_pnl)">
              {{ row.total_pnl != null ? formatNumber(row.total_pnl) : '--' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="日涨跌幅" width="100" align="right" sortable sort-by="nav_change_pct">
          <template #default="{ row }">
            <span :class="pnlClass(row.nav_change_pct)">
              {{ row.nav_change_pct != null ? Number(row.nav_change_pct).toFixed(2) + '%' : '--' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="日涨跌额" width="120" align="right" sortable sort-by="daily_pnl">
          <template #default="{ row }">
            <span :class="pnlClass(row.daily_pnl)">
              {{ row.daily_pnl != null ? formatNumber(row.daily_pnl) : '--' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <el-button
              text type="success" size="small"
              @click.stop="openChangeDialog(row, 'increase')"
            >加仓</el-button>
            <el-button
              text type="warning" size="small"
              @click.stop="openChangeDialog(row, 'decrease')"
            >减仓</el-button>
            <el-popconfirm
              title="确定删除这笔持仓？"
              confirm-button-text="删除"
              cancel-button-text="取消"
              @confirm.stop="handleDelete(row)"
              @click.stop
            >
              <template #reference>
                <el-button
                  text
                  type="danger"
                  size="small"
                  :icon="Delete"
                  @click.stop
                >
                  删除
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="filteredHoldings.length > pageSize"
        class="table-pagination"
        layout="total, prev, pager, next, sizes"
        :total="filteredHoldings.length"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :current-page="currentPage"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </el-card>

    <!-- Cost Edit Dialog -->
    <el-dialog
      v-model="costDialogVisible"
      title="编辑成本净值"
      width="400px"
      destroy-on-close
    >
      <div v-if="editingHolding" style="margin-bottom: 16px">
        <p style="margin: 0 0 8px">{{ editingHolding.fund_code }} - {{ editingHolding.fund_name }}</p>
        <p style="margin: 0; color: #909399; font-size: 13px">
          平台：{{ editingHolding.platform }}｜账户：{{ editingHolding.fund_account }}
        </p>
      </div>
      <el-form @submit.prevent="saveCost">
        <el-form-item label="成本净值">
          <el-input-number
            v-model="editCostNav"
            :precision="4"
            :step="0.01"
            :min="0"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="costDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="costSaving" @click="saveCost">保存</el-button>
      </template>
    </el-dialog>

    <!-- Create Holding Dialog -->
    <el-dialog
      v-model="createDialogVisible"
      title="新增持仓"
      width="500px"
      destroy-on-close
    >
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="100px"
        label-position="top"
        @submit.prevent="submitCreate"
      >
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="基金代码" prop="fund_code">
              <el-input v-model="createForm.fund_code" placeholder="如 110011" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="基金名称" prop="fund_name">
              <el-input v-model="createForm.fund_name" placeholder="基金全称" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="平台" prop="platform">
              <el-select v-model="createForm.platform" placeholder="销售平台" filterable allow-create style="width: 100%">
                <el-option
                  v-for="p in platformOptions"
                  :key="p"
                  :label="p"
                  :value="p"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="持有份额" prop="shares">
              <el-input-number
                v-model="createForm.shares"
                :precision="4"
                :step="100"
                :min="0.0001"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="份额日期" prop="share_date">
              <el-date-picker
                v-model="createForm.share_date"
                type="date"
                placeholder="选择日期"
                style="width: 100%"
                value-format="YYYY-MM-DD"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="成本净值" prop="cost_nav">
              <el-input-number
                v-model="createForm.cost_nav"
                :precision="4"
                :step="0.01"
                :min="0"
                :placeholder="'可选'"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="账户别名" prop="fund_account">
              <el-input v-model="createForm.fund_account" placeholder="如 支付宝主账户" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="交易账户别名" prop="trade_account">
              <el-input v-model="createForm.trade_account" placeholder="可选，默认同账户别名" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="基金公司" prop="management_company">
              <el-input v-model="createForm.management_company" placeholder="可选" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="导入时净值" prop="nav_on_import">
              <el-input-number
                v-model="createForm.nav_on_import"
                :precision="4"
                :step="0.01"
                :min="0"
                :placeholder="'可选'"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSaving" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>

    <!-- Change Holding Dialog (RFC-011) -->
    <el-dialog
      v-model="changeDialogVisible"
      :title="changeType === 'increase' ? '加仓' : '减仓'"
      width="420px"
    >
      <el-form label-width="110px">
        <el-form-item label="基金">
          <span>{{ changeTarget?.fund_name }}</span>
        </el-form-item>
        <el-form-item label="持仓位置">
          <span>{{ changeTarget?.platform }} / {{ changeTarget?.fund_account }}</span>
        </el-form-item>
        <el-form-item label="当前份额">
          <span>{{ formatShares(changeTarget?.shares) }}</span>
        </el-form-item>
        <el-form-item label="业务日期" required>
          <el-date-picker
            v-model="changeBusinessDate"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
            placeholder="平台确认日期"
          />
        </el-form-item>
        <el-form-item :label="changeType === 'increase' ? '实际支付(元)' : '实际到账(元)'">
          <el-input-number
            v-model="changeAmount"
            :min="0.01"
            :precision="2"
            :step="10"
            controls-position="right"
            style="width: 100%"
            placeholder="平台确认金额"
          />
        </el-form-item>
        <el-form-item :label="changeType === 'increase' ? '确认增加份额' : '确认卖出份额'">
          <el-input-number
            v-model="changeConfirmedShares"
            :min="0.0001"
            :precision="4"
            :step="1"
            :controls="false"
            style="width: 100%"
            placeholder="优先填写平台最终确认份额"
          />
        </el-form-item>
        <el-form-item label="确认净值">
          <el-input-number
            v-model="changeNavInput"
            :min="0"
            :precision="4"
            :controls="false"
            style="width: 100%"
            placeholder="可选；留空时按金额/份额推导"
          />
        </el-form-item>
        <el-form-item v-if="changePreview">
          <el-alert :title="changePreview" type="info" :closable="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="changeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="changeSaving" @click="submitChange">确认{{ changeType === 'increase' ? '加仓' : '减仓' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Refresh, Edit, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getHoldings,
  getPlatforms,
  updateHoldingCost,
  createHolding,
  deleteHolding,
  changeHolding,
} from '../api/index.js'

const router = useRouter()

const loading = ref(false)
const holdings = ref([])
const searchKeyword = ref('')
const selectedPlatform = ref('')
const currentPage = ref(1)
const pageSize = ref(50)
const platformOptions = ref([])

// Cost edit state
const costDialogVisible = ref(false)
const editingHolding = ref(null)
const editCostNav = ref(null)
const costSaving = ref(false)

// Create holding state
const createDialogVisible = ref(false)
const createFormRef = ref(null)
const createSaving = ref(false)

// Change holding state (RFC-011)
const changeDialogVisible = ref(false)
const changeTarget = ref(null)
const changeType = ref('increase')
const changeAmount = ref(null)
const changeConfirmedShares = ref(null)
const changeNavInput = ref(null)
const changeBusinessDate = ref('')
const changeSaving = ref(false)
const changePreview = computed(() => {
  if (!changeTarget.value || (!changeAmount.value && !changeConfirmedShares.value)) return ''
  const inferredNav = changeAmount.value && changeConfirmedShares.value
    ? changeAmount.value / changeConfirmedShares.value
    : null
  const nav = changeNavInput.value || inferredNav || changeTarget.value.latest_nav
  const delta = changeConfirmedShares.value || (nav && changeAmount.value ? changeAmount.value / nav : 0)
  if (!delta || delta <= 0) return '请填写实际金额或平台确认份额'
  if (changeType.value === 'increase') {
    const oldShares = Number(changeTarget.value.shares || 0)
    const newShares = oldShares + delta
    if (changeTarget.value.cost_nav == null) {
      return `将新增 ${delta.toFixed(4)} 份 → 新份额 ${newShares.toFixed(4)}；原成本未知，更新后继续标记为未知`
    }
    const oldCost = Number(changeTarget.value.cost_nav)
    const operationAmount = changeAmount.value || delta * nav
    const newCost = (oldShares * oldCost + operationAmount) / newShares
    return `将新增 ${delta.toFixed(4)} 份 → 新份额 ${newShares.toFixed(4)}，新平均成本价约 ${newCost.toFixed(4)}`
  } else {
    const oldShares = Number(changeTarget.value.shares || 0)
    if (delta > oldShares) return `卖出份额超过当前 ${oldShares.toFixed(4)} 份，系统将拒绝保存`
    const newShares = oldShares - delta
    return `将卖出 ${delta.toFixed(4)} 份 → 剩余 ${newShares.toFixed(4)} 份${newShares === 0 ? '（将清仓）' : ''}`
  }
})

function openChangeDialog(row, type) {
  changeTarget.value = row
  changeType.value = type
  changeAmount.value = null
  changeConfirmedShares.value = null
  changeNavInput.value = null
  changeBusinessDate.value = localDateString()
  changeDialogVisible.value = true
}

async function submitChange() {
  if ((!changeAmount.value || changeAmount.value <= 0) && (!changeConfirmedShares.value || changeConfirmedShares.value <= 0)) {
    ElMessage.warning('请填写实际金额或平台确认份额')
    return
  }
  if (!changeBusinessDate.value) {
    ElMessage.warning('请选择业务日期')
    return
  }
  changeSaving.value = true
  try {
    const payload = {
      change_type: changeType.value,
      business_date: changeBusinessDate.value,
    }
    if (changeAmount.value) payload.amount = changeAmount.value
    if (changeConfirmedShares.value) payload.confirmed_shares = changeConfirmedShares.value
    if (changeNavInput.value) payload.cost_nav_input = changeNavInput.value
    const res = await changeHolding(changeTarget.value.id, payload)
    ElMessage.success(res.message || '操作成功')
    changeDialogVisible.value = false
    await loadHoldings()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  } finally {
    changeSaving.value = false
  }
}

const createForm = reactive({
  fund_code: '',
  fund_name: '',
  platform: '',
  fund_account: '',
  trade_account: '',
  shares: 0,
  share_date: '',
  cost_nav: null,
  management_company: '',
  nav_on_import: null,
})
const createRules = {
  fund_code: [{ required: true, message: '请输入基金代码', trigger: 'blur' }],
  fund_name: [{ required: true, message: '请输入基金名称', trigger: 'blur' }],
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  fund_account: [{ required: true, message: '请输入账户别名', trigger: 'blur' }],
  shares: [{ required: true, message: '请输入持有份额', trigger: 'blur' }],
  share_date: [{ required: true, message: '请选择份额日期', trigger: 'change' }],
}

// ---- Computed ----

const filteredHoldings = computed(() => {
  let list = holdings.value
  if (selectedPlatform.value) {
    list = list.filter((holding) => holding.platform === selectedPlatform.value)
  }
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    list = list.filter(
      (h) =>
        h.fund_code?.toLowerCase().includes(kw) ||
        h.fund_name?.toLowerCase().includes(kw)
    )
  }
  return list
})

// 将不同平台的同一基金汇总展示，但保留平台级明细用于实际操作。
const groupedHoldings = computed(() => {
  const groups = new Map()
  for (const holding of filteredHoldings.value) {
    const key = holding.fund_code
    const current = groups.get(key) || {
      fund_code: holding.fund_code,
      fund_name: holding.fund_name,
      platforms: [],
      holding_count: 0,
      total_shares: 0,
      total_market_value: 0,
      total_pnl: 0,
      pnl_complete: true,
    }
    if (!current.platforms.includes(holding.platform)) current.platforms.push(holding.platform)
    current.holding_count += 1
    current.total_shares += Number(holding.shares || 0)
    current.total_market_value += Number(holding.current_market_value || holding.market_value || 0)
    if (holding.total_pnl == null) current.pnl_complete = false
    else current.total_pnl += Number(holding.total_pnl)
    groups.set(key, current)
  }
  return [...groups.values()]
    .map((item) => ({ ...item, total_pnl: item.pnl_complete ? item.total_pnl : null }))
    .sort((left, right) => right.total_market_value - left.total_market_value)
})

const pagedHoldings = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredHoldings.value.slice(start, start + pageSize.value)
})

const totalMarketValue = computed(() => {
  const total = filteredHoldings.value.reduce((sum, h) => {
    return sum + Number(h.current_market_value || h.market_value || 0)
  }, 0)
  return total.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
})

// ---- Format helpers ----

function formatNumber(val) {
  if (val == null) return '--'
  return Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// 份额最多保留四位小数，避免与人民币金额混用两位格式。
function formatShares(val) {
  if (val == null) return '--'
  return Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 4 })
}

// 使用本地日期，避免 UTC 转换导致业务日期偏移。
function localDateString() {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function pnlClass(rate) {
  if (rate == null) return ''
  return Number(rate) > 0 ? 'text-profit' : Number(rate) < 0 ? 'text-loss' : ''
}

// ---- Handlers ----

function handleSearch() {
  currentPage.value = 1
}

function handlePlatformChange() {
  currentPage.value = 1
}

function handlePageChange(page) {
  currentPage.value = page
}

function handleSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
}

function handleRowClick(row) {
  router.push(`/funds/${row.fund_code}`)
}

function handleSummaryRowClick(row) {
  router.push(`/funds/${row.fund_code}`)
}

function goQuickImport() {
  router.push('/import#quick')
}

async function handleDelete(row) {
  try {
    await deleteHolding(row.id)
    ElMessage.success(`已删除 ${row.fund_name}`)
    loadHoldings()
  } catch {
    // 删除错误由统一拦截器提示。
  }
}

// ---- Cost Edit ----

function openCostEdit(row) {
  editingHolding.value = row
  editCostNav.value = row.cost_nav ? Number(row.cost_nav) : null
  costDialogVisible.value = true
}

async function saveCost() {
  if (editCostNav.value == null || editCostNav.value < 0) {
    ElMessage.warning('请输入有效的成本净值')
    return
  }
  costSaving.value = true
  try {
    await updateHoldingCost(editingHolding.value.id, editCostNav.value)
    ElMessage.success('成本净值已更新')
    costDialogVisible.value = false
    loadHoldings()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '精确录入失败')
  } finally {
    costSaving.value = false
  }
}

// ---- Create Holding ----

function openCreateDialog() {
  createForm.fund_code = ''
  createForm.fund_name = ''
  createForm.platform = ''
  createForm.fund_account = ''
  createForm.trade_account = ''
  createForm.shares = 0
  createForm.share_date = ''
  createForm.cost_nav = null
  createForm.management_company = ''
  createForm.nav_on_import = null
  createDialogVisible.value = true
  // Clear validation on next tick
  setTimeout(() => {
    createFormRef.value?.clearValidate()
  }, 0)
}

async function submitCreate() {
  if (!createFormRef.value) return
  try {
    await createFormRef.value.validate()
  } catch {
    return
  }
  createSaving.value = true
  try {
    const payload = {
      fund_code: createForm.fund_code,
      fund_name: createForm.fund_name,
      platform: createForm.platform,
      fund_account: createForm.fund_account,
      trade_account: createForm.trade_account || createForm.fund_account,
      shares: createForm.shares,
      share_date: createForm.share_date,
    }
    if (createForm.cost_nav != null) payload.cost_nav = createForm.cost_nav
    if (createForm.management_company) payload.management_company = createForm.management_company
    if (createForm.nav_on_import != null) payload.nav_on_import = createForm.nav_on_import

    await createHolding(payload)
    ElMessage.success('持仓创建成功')
    createDialogVisible.value = false
    loadHoldings()
  } catch {
    // handled by interceptor
  } finally {
    createSaving.value = false
  }
}

// ---- Delete (context menu, simple confirm) ----

// ---- Data loading ----

async function loadHoldings() {
  loading.value = true
  try {
    holdings.value = await getHoldings({})
  } catch {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

async function loadPlatforms() {
  try {
    platformOptions.value = await getPlatforms()
  } catch {
    // ignore
  }
}

onMounted(() => {
  loadPlatforms()
  loadHoldings()
})
</script>

<style scoped>
.holdings-view {
  padding: 4px;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.toolbar-card {
  margin-bottom: 16px;
}

.summary-text {
  color: #606266;
  font-size: 13px;
}

.text-bold {
  font-weight: 600;
}

.table-card {
  margin-bottom: 20px;
}

.summary-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.summary-hint {
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.platform-tag {
  margin-right: 6px;
  margin-bottom: 2px;
}

.table-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}

.text-profit {
  color: #f56c6c;
  font-weight: 500;
}

.text-loss {
  color: #67c23a;
  font-weight: 500;
}

.editable-cell {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.editable-cell:hover {
  color: #409eff;
}

.edit-icon {
  opacity: 0.3;
}

.editable-cell:hover .edit-icon {
  opacity: 1;
}

:deep(.el-table) {
  cursor: pointer;
}
</style>
