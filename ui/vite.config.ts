/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const uiRoot = fileURLToPath(new URL('.', import.meta.url));
const repoRoot = fileURLToPath(new URL('..', import.meta.url));
// The dev UI proxies to agent A; set TELEPORT_AGENT=http://127.0.0.1:8766 to proxy to B instead.
const agent = process.env.TELEPORT_AGENT ?? 'http://127.0.0.1:8765';

export default defineConfig({
  root: uiRoot,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@contract': fileURLToPath(new URL('../contract/contract.ts', import.meta.url)),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: [repoRoot] },
    proxy: {
      '/api': agent,
      '/ws': { target: agent.replace(/^http/, 'ws'), ws: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
  test: {
    dir: repoRoot,
    include: ['ui/src/**/*.test.{ts,tsx}', 'tests/ui/**/*.test.{ts,tsx}'],
    exclude: ['**/node_modules/**', 'tests/ui/e2e/**'],
    environment: 'jsdom',
    setupFiles: [fileURLToPath(new URL('./src/test-setup.ts', import.meta.url))],
  },
});
