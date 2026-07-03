import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // During `npm run dev`, forward API/auth calls to the FastAPI dashboard
    // (run separately with `python run_dashboard.py`) so you don't have to
    // rebuild the frontend on every change while developing.
    proxy: {
      '/api': 'http://localhost:8000',
      '/login': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
    },
  },
})
