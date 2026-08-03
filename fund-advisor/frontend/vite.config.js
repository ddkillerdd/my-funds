import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8200',
        changeOrigin: true,
        // 长请求(AI 研判可达 70s+) 需放宽容许, 避免 proxy 中断导致前端拿到空 body
        proxyTimeout: 300000,
        timeout: 300000,
      },
    },
  },
})
