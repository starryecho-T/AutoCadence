import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期代理：前端 5173 → 后端 127.0.0.1:8765（CORS 默认也放行 5173，双保险）
// 生产构建后建议由 FastAPI 直接托管 dist/（同源，无需 CORS）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8765', changeOrigin: true },
      '/openapi.json': { target: 'http://127.0.0.1:8765', changeOrigin: true }
    }
  },
  build: { outDir: 'dist', sourcemap: false }
})
