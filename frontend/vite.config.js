import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
      },
      // WebSocket 反代（规划任务实时推送；与后端 /ws 前缀一致）
      '/ws': {
        target: 'ws://127.0.0.1:8090',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})