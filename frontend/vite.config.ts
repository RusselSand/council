import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../backend/spec_council/static', emptyOutDir: true },
  server: { port: 5420, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8420' } },
  test: { environment: 'jsdom' },
})
