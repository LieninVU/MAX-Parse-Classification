import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0', // Слушаем все интерфейсы (IPv4 + IPv6)
    port: 3000,
    proxy: {
      '/api': 'http://localhost:5000', // Проксируем API-запросы на Express
    },
  },
})
