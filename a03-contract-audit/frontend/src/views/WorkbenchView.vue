<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadRawFile } from 'element-plus'
import {
  auditContract,
  getRisks,
  parseContract,
  updateRiskStatus,
  uploadContract,
} from '@/api/contract'
import type { RiskOut } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const contractId = ref<number | null>(null)
const filename = ref('')
const elements = ref<Record<string, unknown> | null>(null)
const risks = ref<RiskOut[]>([])
const busy = ref(false)
const step = ref(0) // 0 未上传 1 已上传解析 2 已审查

// el-upload 手动上传：拦截默认行为，走我们的接口
async function onFile(file: UploadRawFile) {
  busy.value = true
  try {
    const c = await uploadContract(file)
    contractId.value = c.id
    filename.value = c.filename
    ElMessage.success('上传成功，正在解析…')
    const parsed = await parseContract(c.id)
    elements.value = parsed.elements
    risks.value = []
    step.value = 1
    ElMessage.success('解析完成')
  } catch {
    ElMessage.error('上传或解析失败')
  } finally {
    busy.value = false
  }
  return false
}

async function onAudit() {
  if (!contractId.value) return
  busy.value = true
  try {
    await auditContract(contractId.value)
    risks.value = await getRisks(contractId.value)
    step.value = 2
    ElMessage.success(`审查完成，检出 ${risks.value.length} 条风险`)
  } catch {
    ElMessage.error('审查失败（需 legal/finance 角色）')
  } finally {
    busy.value = false
  }
}

async function onStatusChange(risk: RiskOut, status: RiskOut['review_status']) {
  try {
    await updateRiskStatus(risk.id, status)
    risk.review_status = status
    ElMessage.success('已更新复核状态')
  } catch {
    ElMessage.error('更新失败')
  }
}

function logout() {
  auth.logout()
  router.push('/login')
}

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}
const statusLabel: Record<string, string> = {
  pending: '待处理',
  confirmed: '已确认',
  ignored: '已忽略',
  to_modify: '需修改',
}
const elementLabels: Record<string, string> = {
  party_a: '甲方',
  party_b: '乙方',
  amount: '合同金额',
  sign_date: '签订日期',
  duration: '履约期限',
}
</script>

<template>
  <el-container style="height: 100vh">
    <el-header class="header">
      <span class="brand">契鉴 · 合规审查工作台</span>
      <span class="right">
        <el-tag size="small">{{ auth.role }}</el-tag>
        <el-button link type="primary" @click="logout">退出</el-button>
      </span>
    </el-header>

    <el-main>
      <el-steps :active="step" finish-status="success" simple style="margin-bottom: 20px">
        <el-step title="上传合同" />
        <el-step title="解析要素" />
        <el-step title="合规审查" />
      </el-steps>

      <el-row :gutter="16">
        <!-- 左：上传 + 要素 -->
        <el-col :span="9">
          <el-card shadow="never">
            <template #header>1. 上传合同（PDF / Word / txt）</template>
            <el-upload
              drag
              :auto-upload="true"
              :show-file-list="false"
              :http-request="() => {}"
              :before-upload="onFile"
              accept=".pdf,.docx,.txt"
            >
              <el-icon class="el-icon--upload"><upload-filled /></el-icon>
              <div class="el-upload__text">拖拽文件到此，或<em>点击选择</em></div>
            </el-upload>

            <div v-if="filename" class="filename">当前：{{ filename }}（合同 #{{ contractId }}）</div>

            <template v-if="elements">
              <el-divider content-position="left">解析出的关键要素</el-divider>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item
                  v-for="(label, key) in elementLabels"
                  :key="key"
                  :label="label"
                >
                  <span v-if="elements[key]">{{ elements[key] }}</span>
                  <el-text v-else type="danger">未检出</el-text>
                </el-descriptions-item>
              </el-descriptions>
              <el-button
                type="primary"
                style="margin-top: 16px; width: 100%"
                :loading="busy"
                @click="onAudit"
              >
                2. 开始合规审查
              </el-button>
            </template>
          </el-card>
        </el-col>

        <!-- 右：风险清单 -->
        <el-col :span="15">
          <el-card shadow="never">
            <template #header>
              3. 风险清单
              <el-tag v-if="risks.length" type="danger" size="small">{{ risks.length }} 条</el-tag>
            </template>

            <el-empty v-if="step < 2" description="完成审查后在此显示风险" />

            <div v-for="r in risks" :key="r.id" class="risk-item">
              <div class="risk-head">
                <el-tag :type="levelMeta[r.level].type" size="small">
                  {{ levelMeta[r.level].label }}风险
                </el-tag>
                <span class="risk-cat">{{ r.category }}</span>
                <el-tag size="small" effect="plain">置信度 {{ r.confidence }}</el-tag>
                <el-tag size="small" effect="plain" style="margin-left: auto">
                  {{ statusLabel[r.review_status] }}
                </el-tag>
              </div>
              <p class="risk-line"><b>原文：</b>{{ r.original_text }}</p>
              <p class="risk-line"><b>依据：</b>{{ r.basis }}</p>
              <p class="risk-line"><b>建议：</b>{{ r.suggestion }}</p>
              <div class="risk-actions">
                <el-button size="small" type="success" @click="onStatusChange(r, 'confirmed')">确认</el-button>
                <el-button size="small" @click="onStatusChange(r, 'ignored')">忽略</el-button>
                <el-button size="small" type="warning" @click="onStatusChange(r, 'to_modify')">需修改</el-button>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-main>
  </el-container>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #ebeef5;
}
.brand {
  font-weight: 600;
  color: #1e3a5f;
}
.right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.filename {
  margin-top: 12px;
  font-size: 13px;
  color: #606266;
}
.risk-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.risk-cat {
  font-weight: 600;
}
.risk-line {
  margin: 4px 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
.risk-actions {
  margin-top: 8px;
}
</style>
