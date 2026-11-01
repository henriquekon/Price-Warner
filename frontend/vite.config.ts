import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://127.0.0.1:9873',
      '/dashboard': 'http://127.0.0.1:9873',
      '/products': 'http://127.0.0.1:9873',
      '/stores': 'http://127.0.0.1:9873',
      '/notifications': 'http://127.0.0.1:9873',
    },
  },
});
