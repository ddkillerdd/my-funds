<template>
  <div class="import-view">
    <h2 class="page-title">数据导入</h2>

    <!-- Quick Import (RFC-002) -->
    <el-card shadow="hover" class="quick-import-card">
      <template #header>
        <span>📝 快捷导入 — 只需基金代码 + 持有金额</span>
      </template>

      <div class="quick-import-form">
        <el-input
          v-model="quickFundCode"
          placeholder="基金代码（如 018044）"
          class="quick-code-input"
          clearable
          @keyup.enter="addQuickRecord"
        />
        <el-input
          v-model="quickAmount"
          placeholder="持有金额（元）"
          class="quick-amount-input"
          clearable
          @keyup.enter="addQuickRecord"
        >
          <template #prefix>¥</template>
        </el-input>
        <el-button type="primary" :icon="Plus" @click="addQuickRecord">添加</el-button>
      </div>

      <!-- Quick Import Preview -->
      <div v-if="quickRecords.length > 0" class="quick-preview">
        <el-table :data="quickRecords" stripe max-height="300">
          <el-table-column prop="fund_code" label="基金代码" width="110" />
          <el-table-column prop="fund_name" label="基金名称" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row._resolved_name" class="text-resolved">{{ row._resolved_name }}</span>
              <span v-else class="text-pending">待查询</span>
            </template>
          </el-table-column>
          <el-table-column label="持有金额" width="120" align="right">
            <template #default="{ row }">
              ¥{{ Number(row.market_value).toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column label="份额" width="150" align="right">
            <template #default="{ row }">
              <span v-if="row._shares_hint" class="text-resolved">{{ formatShares(row._shares_hint) }}</span>
              <el-tag v-else size="small" type="warning">待净值</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="平台" width="120">
            <template #default="{ row }">
              <el-select v-model="row.platform" size="small" style="width: 100px">
                <el-option label="支付宝" value="支付宝" />
                <el-option label="天天基金" value="天天基金" />
                <el-option label="银行" value="银行" />
                <el-option label="其他" value="其他" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="60" align="center">
            <template #default="{ $index }">
              <el-button type="danger" :icon="Delete" size="small" link @click="quickRecords.splice($index, 1)" />
            </template>
          </el-table-column>
        </el-table>

        <div class="quick-import-actions">
          <el-button
            type="primary"
            :icon="Upload"
            :loading="quickImporting"
            @click="handleQuickImport"
          >
            批量导入 ({{ quickRecords.length }} 条)
          </el-button>
          <el-button @click="quickRecords = []">清空列表</el-button>
        </div>
      </div>
    </el-card>

    <!-- Upload Area (existing) -->
    <el-card shadow="hover" class="upload-card">
      <template #header>
        <span>上传持仓文件</span>
      </template>

      <el-upload
        ref="uploadRef"
        class="upload-area"
        drag
        action=""
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.xls,.zip"
        :on-change="handleFileChange"
        :on-exceed="handleExceed"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          将基金E账户导出的 Excel 或 ZIP 文件拖到此处，或 <em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持 .xlsx、.xls 或 .zip 格式（ZIP可包含多个Excel文件）。文件来源：基金E账户App → 投资者公募基金持有信息
          </div>
        </template>
      </el-upload>

      <div class="upload-actions">
        <el-button
          type="primary"
          :icon="Upload"
          :loading="uploading"
          :disabled="!selectedFile"
          @click="handleUpload"
        >
          开始导入
        </el-button>
      </div>
    </el-card>

    <!-- Import Result -->
    <el-card v-if="importResult" shadow="hover" class="result-card">
      <template #header>
        <span>导入结果</span>
      </template>
      <el-result
        :icon="resultIcon"
        :title="resultTitle"
        :sub-title="importResult.error_message || ''"
      >
        <template #extra>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="数据日期">{{ importResult.data_date ?? '--' }}</el-descriptions-item>
            <el-descriptions-item label="总记录数">{{ importResult.total_rows ?? 0 }}</el-descriptions-item>
            <el-descriptions-item label="新增持仓">
              <el-tag type="success" size="small">{{ importResult.new_holdings ?? 0 }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="更新持仓">
              <el-tag type="primary" size="small">{{ importResult.updated_holdings ?? 0 }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="清仓标记">
              <el-tag type="warning" size="small">{{ importResult.removed_holdings ?? 0 }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="解析错误">
              <el-tag type="danger" size="small">{{ importResult.error_rows ?? 0 }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <div v-if="importResult.changes && importResult.changes.length" style="margin-top: 12px">
            <el-button type="primary" link @click="showChangesFromResult">
              查看变动明细（{{ importResult.changes.length }} 条）
            </el-button>
          </div>
        </template>
      </el-result>
    </el-card>

    <!-- Import History -->
    <el-card shadow="hover" class="history-card">
      <template #header>
        <span>导入历史</span>
      </template>
      <el-table :data="importHistory" stripe style="width: 100%" v-loading="historyLoading">
        <el-table-column prop="created_at" label="导入时间" width="180" />
        <el-table-column prop="file_name" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="data_date" label="数据日期" width="120" />
        <el-table-column prop="total_rows" label="记录数" width="80" align="center" />
        <el-table-column prop="new_holdings" label="新增" width="70" align="center" />
        <el-table-column prop="updated_holdings" label="更新" width="70" align="center" />
        <el-table-column prop="status" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'success' || row.status === 'partial'"
              type="primary"
              link
              size="small"
              @click="loadChanges(row.id)"
            >
              查看变动
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Changes Dialog -->
    <el-dialog
      v-model="changesDialogVisible"
      title="持仓变动明细"
      width="900px"
      destroy-on-close
    >
      <el-table :data="changesData" stripe v-loading="changesLoading" max-height="500">
        <el-table-column prop="fund_code" label="基金代码" width="100" />
        <el-table-column prop="fund_name" label="基金名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="120" show-overflow-tooltip />
        <el-table-column label="变动类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="changeTypeTag(row.change_type)" size="small">
              {{ changeTypeLabel(row.change_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="份额变化" width="200" align="right">
          <template #default="{ row }">
            <span>{{ formatNum(row.shares_before) }} → {{ formatNum(row.shares_after) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="变动量" width="130" align="right">
          <template #default="{ row }">
            <span :class="deltaClass(row.shares_delta)">
              {{ row.shares_delta > 0 ? '+' : '' }}{{ formatNum(row.shares_delta) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { UploadFilled, Upload, Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { uploadExcel, getImportHistory, getImportChanges, simpleImport } from '../api/index.js'

const uploadRef = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const importResult = ref(null)
const importHistory = ref([])
const historyLoading = ref(false)

// Quick Import (RFC-002)
const quickFundCode = ref('')
const quickAmount = ref('')
const quickRecords = ref([])
const quickImporting = ref(false)

const changesDialogVisible = ref(false)
const changesData = ref([])
const changesLoading = ref(false)

const resultTitle = computed(() => {
  if (!importResult.value) return ''
  const s = importResult.value.status
  if (s === 'success') return '导入成功'
  if (s === 'duplicate') return '文件已导入过'
  if (s === 'partial') return '部分成功'
  return '导入失败'
})

const resultIcon = computed(() => {
  if (!importResult.value) return 'error'
  const s = importResult.value.status
  if (s === 'success') return 'success'
  if (s === 'duplicate') return 'warning'
  if (s === 'partial') return 'warning'
  return 'error'
})

function statusLabel(status) {
  const map = { success: '成功', duplicate: '重复', partial: '部分成功', error: '失败' }
  return map[status] ?? status
}

function statusTagType(status) {
  const map = { success: 'success', duplicate: 'warning', partial: 'warning', error: 'danger' }
  return map[status] ?? 'info'
}

function changeTypeLabel(type) {
  const map = { new: '新增', increase: '加仓', decrease: '减仓', clear: '清仓' }
  return map[type] ?? type
}

function changeTypeTag(type) {
  const map = { new: 'success', increase: 'primary', decrease: 'warning', clear: 'danger' }
  return map[type] ?? 'info'
}

function formatNum(val) {
  if (val == null) return '--'
  return Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function deltaClass(val) {
  if (val == null) return ''
  return Number(val) > 0 ? 'text-profit' : Number(val) < 0 ? 'text-loss' : ''
}

function handleFileChange(file) {
  selectedFile.value = file.raw
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件，请先移除已选文件')
}

// ---- Quick Import (RFC-002) ----

function addQuickRecord() {
  const code = quickFundCode.value.trim()
  const amount = parseFloat(quickAmount.value)
  if (!code) {
    ElMessage.warning('请输入基金代码')
    return
  }
  if (!amount || amount <= 0) {
    ElMessage.warning('请输入有效的持有金额')
    return
  }
  // Check duplicate
  if (quickRecords.value.some(r => r.fund_code === code)) {
    ElMessage.warning('该基金代码已添加')
    return
  }
  quickRecords.value.push({
    fund_code: code,
    market_value: amount,
    platform: '支付宝',
    _resolved_name: null,
    _shares_hint: null,
  })
  quickFundCode.value = ''
  quickAmount.value = ''
}

async function handleQuickImport() {
  if (quickRecords.value.length === 0) return
  quickImporting.value = true
  try {
    const records = quickRecords.value.map(r => ({
      fund_code: r.fund_code,
      market_value: r.market_value,
      platform: r.platform,
      share_date: new Date().toISOString().slice(0, 10),
    }))
    const res = await simpleImport(records)
    const msg = `成功导入 ${res.success} 条` + (res.errors.length ? `，${res.errors.length} 条失败` : '')
    if (res.errors.length > 0) {
      ElMessage.warning(msg)
    } else {
      ElMessage.success(msg)
    }
    quickRecords.value = []
  } catch {
    ElMessage.error('快捷导入失败')
  } finally {
    quickImporting.value = false
  }
}

function formatShares(val) {
  if (val == null) return '--'
  return Number(val).toLocaleString('zh-CN', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  })
}

async function handleUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  importResult.value = null
  try {
    importResult.value = await uploadExcel(selectedFile.value)
    if (importResult.value.status === 'success') {
      ElMessage.success('导入成功')
      // Auto-show changes if present
      if (importResult.value.changes?.length) {
        changesData.value = importResult.value.changes
        changesDialogVisible.value = true
      }
    } else if (importResult.value.status === 'partial') {
      ElMessage.warning('部分文件导入成功，请查看详细信息')
      if (importResult.value.changes?.length) {
        changesData.value = importResult.value.changes
        changesDialogVisible.value = true
      }
    } else if (importResult.value.status === 'duplicate') {
      ElMessage.warning('该文件已导入过')
    }
    loadHistory()
    uploadRef.value?.clearFiles()
    selectedFile.value = null
  } catch {
    importResult.value = { status: 'error', error_message: '导入过程中发生错误，请检查文件格式' }
  } finally {
    uploading.value = false
  }
}

function showChangesFromResult() {
  if (importResult.value?.changes?.length) {
    changesData.value = importResult.value.changes
    changesDialogVisible.value = true
  }
}

async function loadChanges(importId) {
  changesDialogVisible.value = true
  changesLoading.value = true
  changesData.value = []
  try {
    changesData.value = await getImportChanges(importId)
  } catch {
    // Errors handled by interceptor
  } finally {
    changesLoading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    importHistory.value = await getImportHistory()
  } catch {
    // Errors handled by interceptor
  } finally {
    historyLoading.value = false
  }
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.import-view {
  padding: 4px;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.quick-import-card {
  margin-bottom: 20px;
}

.quick-import-form {
  display: flex;
  gap: 12px;
  align-items: center;
}

.quick-code-input {
  width: 200px;
}

.quick-amount-input {
  width: 180px;
}

.quick-preview {
  margin-top: 16px;
}

.quick-import-actions {
  margin-top: 12px;
  display: flex;
  gap: 10px;
}

.text-resolved {
  color: #67c23a;
}

.text-pending {
  color: #909399;
  font-style: italic;
}

.upload-card {
  margin-bottom: 20px;
}

.upload-area {
  width: 100%;
}

.upload-actions {
  margin-top: 16px;
  text-align: center;
}

.result-card {
  margin-bottom: 20px;
}

.history-card {
  margin-bottom: 20px;
}

.text-profit {
  color: #f56c6c;
  font-weight: 500;
}

.text-loss {
  color: #67c23a;
  font-weight: 500;
}
</style>
