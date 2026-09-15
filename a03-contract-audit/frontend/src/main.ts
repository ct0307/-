import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 卷宗风主题：必须在 element-plus css 之后引入，以覆盖默认蓝
import '@/styles/index.scss'

import App from './App.vue'
import router from './router'
import { registerIcons } from './plugins/icons'
import { initTheme } from './theme/theme'
import { setUnauthorizedHandler } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

initTheme()
const app = createApp(App)

registerIcons(app) // 按需注册项目用到的图标（替代全量注册减包）

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// 401 凭证失效：统一登出（清 store + localStorage）并用 router 跳转，避免整页刷新丢失 SPA 状态
setUnauthorizedHandler(() => {
  useAuthStore().logout()
  if (router.currentRoute.value.name !== 'login') {
    router.push({ name: 'login' })
  }
})

app.mount('#app')
