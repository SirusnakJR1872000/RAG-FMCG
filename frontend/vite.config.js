// Vite + React + Tailwind v4 (PROJECT_SPEC §5.1).
// The dev server forwards /api to the backend, so the browser sees ONE origin: the refresh
// cookie (Path=/api/auth, SameSite=Strict) and the backend's Origin check then just work.
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const API_TARGET = process.env.API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: 'localhost',
    proxy: { '/api': { target: API_TARGET, changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
    restoreMocks: true,
  },
})
