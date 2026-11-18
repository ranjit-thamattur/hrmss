import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const here = path.dirname(fileURLToPath(import.meta.url));
// Client (tenant) folder with tenant.js and theme.css (decision 0006). Set by the client's build
// (services/hotel_vivek_frontend) through TENANT_FRONTEND_DIR; without it the neutral core default is used.
const tenantDir = path.resolve(here, process.env.TENANT_FRONTEND_DIR || './src/tenant-default');

// In development the API runs on :8000; /api is proxied so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@tenant': tenantDir } },
  server: {
    port: 5173,
    host: true,
    fs: { allow: [here, tenantDir] },
    proxy: { '/api': { target: process.env.VITE_API_PROXY || 'http://localhost:8000', changeOrigin: true } },
  },
});
