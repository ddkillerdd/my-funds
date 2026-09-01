import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 本地开发端口与服务器 systemd 服务保持一致。
    port: 8201,
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
