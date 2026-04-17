import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import electron from 'vite-plugin-electron';
import renderer from 'vite-plugin-electron-renderer';
import path from 'path';

export default defineConfig({
  plugins: [
    react(),
    electron([
      {
        entry: 'electron/main.ts',
        onstart(args) {
          args.startup();
        },
        vite: {
          build: {
            outDir: 'dist-electron',
            rollupOptions: {
              external: ['electron'],
            },
          },
          resolve: {
            alias: {
              shared: path.resolve(__dirname, '../shared'),
            },
          },
        },
      },
      {
        entry: 'electron/preload.ts',
        onstart(args) {
          args.reload();
        },
        vite: {
          build: {
            outDir: 'dist-electron',
          },
        },
      },
    ]),
    renderer(),
  ],
  resolve: {
    alias: {
      shared: path.resolve(__dirname, '../shared'),
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    host: true,
    // Keep the inotify footprint small on Linux: skip build outputs and any
    // sibling server directories that the client never needs to reload for.
    //
    // On network/scratch filesystems (NFS, Lustre, GPFS) or on hosts where
    // `fs.inotify.max_user_watches` cannot be raised, set the environment
    // variable `CHOKIDAR_USEPOLLING=1` before `npm run dev` — this makes both
    // tsx-watch (server) and Vite (client) stop using inotify entirely.
    watch: {
      usePolling: !!process.env.CHOKIDAR_USEPOLLING,
      interval: Number(process.env.CHOKIDAR_INTERVAL) || 1000,
      ignored: [
        '**/node_modules/**',
        '**/.git/**',
        '**/dist/**',
        '**/dist-electron/**',
        '**/dist-web/**',
        '**/../server/uploads/**',
        '**/../server/data/**',
        '**/../server/dist/**',
        '**/../server/public/**',
      ],
    },
    proxy: {
      '/auth': 'http://localhost:3000',
      '/rooms': 'http://localhost:3000',
      '/upload': 'http://localhost:3000',
      '/uploads': 'http://localhost:3000',
      '/api': 'http://localhost:3000',
      '/files': 'http://localhost:3000',
      '/health': 'http://localhost:3000',
      '/socket.io': {
        target: 'http://localhost:3000',
        ws: true,
      },
    },
  },
});
