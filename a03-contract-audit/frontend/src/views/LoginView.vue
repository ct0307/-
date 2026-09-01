<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

const isDev = import.meta.env.DEV

// L1：表单校验规则，空字段在输入框下方显示红色 inline 提示
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
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
  <div class="login-shell">
    <!-- 左：品牌展示区（窄屏隐藏） -->
    <aside class="brand-pane">
      <span class="brand-watermark" aria-hidden="true">契</span>
      <div class="brand-content">
        <div class="brand-head">
          <span class="brand-mark seal-badge">契</span>
          <div class="brand-txt">
            <h1 class="brand-name">契鉴</h1>
            <p class="brand-sub">企业合同合规审查系统</p>
          </div>
        </div>
        <ul class="brand-points">
          <li>私有化部署 · 合同数据不出企业</li>
          <li>RAG 可解释审查 · 每条风险可溯源到法条</li>
          <li>法务 / 财务双 Agent 协同 · 人工复核闭环</li>
        </ul>
        <p class="brand-foot">合同风险体检 · 合规留痕 · 一站交付</p>
      </div>
    </aside>

    <!-- 右：登录表单区 -->
    <main class="form-pane">
      <div class="login-card">
        <!-- 窄屏下品牌区隐藏，卡片内补一个精简品牌头 -->
        <div class="card-brand">
          <span class="brand-mark seal-badge">契</span>
          <div>
            <h2 class="card-title">契鉴</h2>
            <p class="card-sub">企业合同合规审查系统</p>
          </div>
        </div>
        <p class="form-lead">账号登录</p>
        <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="onSubmit">
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              size="large"
              name="username"
              autocomplete="username"
              :prefix-icon="'User'"
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
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
    </main>
  </div>
</template>

<style scoped>
/* 整体：左右分栏，填满视口，天然随屏缩放，卡片不再飘 */
.login-shell {
  height: 100vh;
  display: flex;
  overflow: hidden;
}

/* ============ 左：品牌展示区 ============ */
.brand-pane {
  position: relative;
  flex: 1.15 1 0;
  min-width: 0;
  display: flex;
  align-items: center;
  padding: 0 clamp(48px, 7vw, 120px);
  background:
    radial-gradient(120% 100% at 0% 0%, var(--login-glow) 0%, var(--ink) 60%),
    var(--ink);
  border-right: 1px solid var(--line);
  overflow: hidden;
}
/* 超大半透明"契"水印，提供视觉重心 */
.brand-watermark {
  position: absolute;
  right: -3vw;
  bottom: -8vh;
  font-family: var(--serif);
  font-weight: 700;
  font-size: 46vh;
  line-height: 1;
  color: var(--seal-watermark);
  user-select: none;
  pointer-events: none;
}
.brand-content {
  position: relative;
  z-index: 1;
  max-width: 460px;
}
.brand-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}
.brand-head .brand-mark {
  width: 52px;
  height: 52px;
  font-size: 26px;
}
.brand-name {
  margin: 0;
  font-family: var(--serif);
  font-size: 40px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--ivory);
}
.brand-sub {
  margin: 4px 0 0;
  font-size: 14px;
  letter-spacing: 0.02em;
  color: var(--ivory-dim);
}
.brand-points {
  list-style: none;
  margin: 0 0 32px;
  padding: 0;
}
.brand-points li {
  position: relative;
  padding-left: 20px;
  margin-bottom: 16px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--ivory-dim);
}
/* 印章朱小方块作项目符 */
.brand-points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 8px;
  height: 8px;
  border: 1.5px solid var(--seal);
  border-radius: 2px;
  background: var(--seal-panel-soft);
}
.brand-foot {
  margin: 0;
  padding-top: 20px;
  border-top: 1px solid var(--line);
  font-family: var(--serif);
  font-size: 13px;
  letter-spacing: 0.03em;
  color: var(--muted);
}

/* ============ 右：登录表单区 ============ */
.form-pane {
  flex: 0.85 1 0;
  min-width: 380px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--ink-2);
}
.login-card {
  width: 100%;
  max-width: 340px;
}
/* 卡内品牌头：仅窄屏（品牌区隐藏时）显示 */
.card-brand {
  display: none;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}
.card-title {
  margin: 0;
  font-family: var(--serif);
  font-size: 22px;
  color: var(--ivory);
}
.card-sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--ivory-dim);
}
.form-lead {
  margin: 0 0 22px;
  font-family: var(--serif);
  font-size: 20px;
  font-weight: 600;
  color: var(--ivory);
}
.hint {
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  margin-top: 16px;
  font-family: var(--mono);
}

/* ============ 响应式：窄屏收起品牌区 ============ */
@media (max-width: 880px) {
  .brand-pane {
    display: none;
  }
  .form-pane {
    flex: 1;
    min-width: 0;
  }
  .card-brand {
    display: flex;
  }
  .form-lead {
    display: none;
  }
}
</style>
