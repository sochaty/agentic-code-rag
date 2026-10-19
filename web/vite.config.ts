/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs on :8000 (`acr serve`); in dev, Vite proxies to it so the app is same-origin.
const api = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: { proxy: { '/api': api, '/healthz': api, '/readyz': api } },
  build: {
    // The rst grammar (~1.5 MB, lazy-loaded only when an .rst citation opens) is the one big chunk.
    chunkSizeWarningLimit: 1600,
    rolldownOptions: {
      output: {
        // Vendor groups change far less often than app code, so they stay cached across releases.
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
            { name: 'flow', test: /node_modules[\\/](@xyflow|d3-[a-z]+)[\\/]/ },
            { name: 'markdown', test: /node_modules[\\/](react-markdown|remark-|rehype-|micromark|mdast-|hast-|unified|vfile)/ },
            { name: 'ui', test: /node_modules[\\/](@base-ui|@floating-ui|lucide-react|@tanstack)/ },
          ],
        },
      },
    },
  },
  test: { environment: 'happy-dom', setupFiles: ['./src/test/setup.ts'], globals: true },
})
