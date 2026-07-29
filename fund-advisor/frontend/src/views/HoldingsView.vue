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
            @change="loadHoldings"
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
          <el-button type="primary" :icon="Plus" @click="openCreateDialog" style="margin-left: 12px">
            新增
          </el-button>
          <el-button :icon="Refresh" @click="loadHoldings">
            刷新
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- Holdings Table -->
    <el-card shadow="hover" class="table-card">
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
        <el-table-column label="持有份额" width="120" align="right" sortable sort-by="shares">
          <template #default="{ row }">
            {{ formatNumber(row.shares) }}
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
        <p style="margin: 0; color: #909399; font-size: 13px">平台: {{ editingHolding.platform }}</p>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Refresh, Edit, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getHoldings,
  getPlatforms,
  updateHoldingCost,
  createHolding,
  deleteHolding,
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
const createForm = reactive({
  fund_code: '',
  fund_name: '',
  platform: '',
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
  shares: [{ required: true, message: '请输入持有份额', trigger: 'blur' }],
  share_date: [{ required: true, message: '请选择份额日期', trigger: 'change' }],
}

// ---- Computed ----

const filteredHoldings = computed(() => {
  let list = holdings.value
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

const pagedHoldings = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredHoldings.value.slice(start, start + pageSize.value)
})

const totalMarketValue = computed(() => {
  const total = holdings.value.reduce((sum, h) => {
    return sum + Number(h.current_market_value || h.market_value || 0)
  }, 0)
  return total.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
})

// ---- Format helpers ----

function formatNumber(val) {
  if (val == null) return '--'
  return Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function pnlClass(rate) {
  if (rate == null) return ''
  return Number(rate) > 0 ? 'text-profit' : Number(rate) < 0 ? 'text-loss' : ''
}

// ---- Handlers ----

function handleSearch() {
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
  } catch {
    // handled by interceptor
  } finally {
    costSaving.value = false
  }
}

// ---- Create Holding ----

function openCreateDialog() {
  createForm.fund_code = ''
  createForm.fund_name = ''
  createForm.platform = ''
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
    const params = {}
    if (selectedPlatform.value) params.platform = selectedPlatform.value
    holdings.value = await getHoldings(params)
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
