/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dashboard talks to the WaterTwin API under /api/v1. In dev we proxy to the
// reference API; in production the built app is served from the API static mount
// so the same relative path works without configuration.
const API_TARGET = process.env.VITE_API_PROXY ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: ['**/node_modules/**', '**/e2e/**', '**/dist/**'],
    // Pin the timezone so date/time formatting in report snapshots is
    // deterministic across contributor machines and CI.
    env: { TZ: 'UTC' },
  },
});
