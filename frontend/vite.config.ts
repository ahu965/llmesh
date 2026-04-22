import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8001', changeOrigin: true },
    },
  },
  build: {
    outDir: '../backend/static/dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('@arco-design/web-vue')) return 'vendor-arco'
          if (id.includes('node_modules/vue') || id.includes('node_modules/vue-router')) return 'vendor-vue'
          if (id.includes('node_modules/')) return 'vendor-misc'
        },
      },
    },
  },
})
