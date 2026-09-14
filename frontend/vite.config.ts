import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = process.env.SOUL_EXTER_BACKEND || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    allowedHosts: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true }
    }
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 2400 }
})
