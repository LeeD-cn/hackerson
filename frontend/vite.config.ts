import { defineConfig } from 'vite';

// This is a server-side setting. No credentials are exposed as VITE_* variables.
const target = process.env.RELAY_API_URL || 'http://127.0.0.1:8765';
const proxy = { '/api': { target, changeOrigin: true }, '/health': { target, changeOrigin: true } };

export default defineConfig({
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
});
