import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  optimizeDeps: {
    // 一次性预构建共享依赖图，避免 ECharts 子入口在开发期落入不同模块实例。
    include: [
      'echarts/core',
      'echarts/charts',
      'echarts/components',
      'echarts/renderers',
    ],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // vendor chunk（element-plus/echarts）体积由第三方库决定，可长期缓存，
    // 阈值调高避免对已主动分包的 vendor chunk 误报。
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // 分包：把大依赖拆出主 chunk，改善缓存与首屏
        manualChunks: {
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          echarts: ['echarts'],
          vue: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 开发期把 /api 代理到后端，避免 CORS
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
})
