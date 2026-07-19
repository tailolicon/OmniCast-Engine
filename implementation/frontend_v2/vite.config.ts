import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../src/omnicast/api/webui_v2',
    emptyOutDir: true,
  },
  base: '/',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8767',
      '/media': 'http://127.0.0.1:8767',
      '/jobengine': 'http://127.0.0.1:8767',
      '/office_app': 'http://127.0.0.1:8767',
    }
  }
});
