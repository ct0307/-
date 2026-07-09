<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

// 不预填演示凭证（生产去除演示痕迹）
const username = ref('')
const password = ref('')
const loading = ref(false)

const isDev = import.meta.env.DEV

async function onSubmit() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } catch {
    ElMessage.error('用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="brand">
        <span class="brand-mark seal-badge">契</span>
        <div class="brand-txt">
          <h2 class="title">契鉴</h2>
          <p class="eyebrow">企业合同合规审查系统</p>
        </div>
      </div>
      <p class="subtitle">私有化部署 · 数据不出企业</p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item>
          <el-input
            v-model="username"
            placeholder="用户名"
            size="large"
            name="username"
            autocomplete="username"
            :prefix-icon="'User'"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="密码"
            size="large"
            show-password
            name="password"
            autocomplete="current-password"
            :prefix-icon="'Lock'"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width: 100%"
          :loading="loading"
          @click="onSubmit"
        >
          登 录
        </el-button>
      </el-form>
      <!-- 演示账号：仅 dev 模式可见，生产构建自动隐藏 -->
      <p v-if="isDev" class="hint">演示账号：legal / legal123 · admin / admin123</p>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--ink);
}
.login-card {
  width: 380px;
  padding: 36px 34px 28px;
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow);
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 6px;
}
.brand-mark {
  width: 48px;
  height: 48px;
  font-size: 24px;
}
.title {
  margin: 0;
  font-size: 22px;
  color: var(--ivory);
}
.eyebrow {
  margin: 2px 0 0;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--brass);
  font-family: var(--mono);
}
.subtitle {
  color: var(--ivory-dim);
  margin: 4px 0 24px;
  font-size: 13px;
}
.hint {
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  margin-top: 16px;
  font-family: var(--mono);
}
</style>
