import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// В докере бек — соседний контейнер, а не localhost; bind-mount с Windows не шлёт
// события файловой системы, поэтому там же включается опрос.
const apiTarget = process.env.VITE_API_PROXY || 'http://127.0.0.1:8420'
const usePolling = process.env.VITE_USE_POLLING === '1'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5420,
    strictPort: true,
    proxy: { '/api': apiTarget },
    ...(usePolling ? { watch: { usePolling: true } } : {}),
  },
  test: { environment: 'jsdom' },
})
