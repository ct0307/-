import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 卷宗风主题：必须在 element-plus css 之后引入，以覆盖默认蓝
import '@/styles/index.scss'

import App from './App.vue'
import router from './router'
import { registerIcons } from './plugins/icons'

const app = createApp(App)

registerIcons(app) // 按需注册项目用到的图标（替代全量注册减包）

app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
