import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
    cacheDir: '../.local/vite-cache',
    build: { outDir: 'dist', emptyOutDir: true },
    server: { host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:5000' } },
    test: { pool: 'threads', maxWorkers: 1, environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'], setupFiles: ['./src/test-setup.ts'] },
});
