import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The backend sits on 8000 and its CORS allow-list names 5173, so direct
    // calls work. The proxy exists for the SSE chat stream: same-origin keeps
    // EventSource-style responses off the CORS preflight path entirely.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
