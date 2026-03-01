import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// Read the port written by run.py so the proxy always targets the live backend.
// Falls back to 8860 if the file doesn't exist (e.g. first run or manual start).
function readBackendPort(): number {
  try {
    const portFile = resolve(__dirname, '..', '.backend-port')
    return parseInt(readFileSync(portFile, 'utf-8').trim(), 10) || 8860
  } catch {
    return 8860
  }
}

const BACKEND = `http://localhost:${readBackendPort()}`

const proxyPaths = [
  '/api', '/system', '/tasks', '/codex', '/router', '/telemetry', '/plans',
  '/context', '/validate', '/ws', '/models', '/sql', '/artifacts', '/workers',
  '/backfill', '/events', '/rag', '/metrics', '/audit', '/feature-flags',
  '/prompt-registry', '/overrides', '/lineage', '/instructions', '/runs',
  '/planner',
]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    proxy: Object.fromEntries(
      proxyPaths.map(path => [
        path,
        { target: BACKEND, changeOrigin: true },
      ])
    ),
  },
  build: {
    outDir: 'dist',
  },
})
