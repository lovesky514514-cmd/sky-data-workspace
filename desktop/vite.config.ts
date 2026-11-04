import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';

export default defineConfig(() => {
  const infoPath = process.env.SKY_PREVIEW_RUNTIME;
  const runtime = infoPath
    ? JSON.parse(fs.readFileSync(infoPath, 'utf8').replace(/^\uFEFF/, ''))
    : null;
  return {
    plugins: [react()],
    clearScreen: false,
    server: {
      host: '127.0.0.1',
      port: 5178,
      strictPort: true,
      watch: { ignored: ['**/src-tauri/**'] },
      proxy: runtime
        ? {
            '/runtime-api': {
              target: runtime.base_url,
              changeOrigin: true,
              rewrite: (path: string) => path.replace(/^\/runtime-api/, ''),
              configure(proxy: any) {
                proxy.on('proxyReq', (request: any) => {
                  request.setHeader('Authorization', 'Bearer ' + runtime.token);
                  request.removeHeader('Origin');
                });
              },
            },
          }
        : undefined,
    },
    build: { target: 'es2022' },
  };
});
