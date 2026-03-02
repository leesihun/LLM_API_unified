import express from 'express';
import { createServer } from 'http';
import { Server } from 'socket.io';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import { initDatabase } from './db/init.js';
import { setupSocketHandlers } from './socket/handler.js';
import { startCleanupCron } from './cron/cleanup.js';
import authRoutes from './routes/auth.js';
import roomRoutes, { setRoomsIo } from './routes/rooms.js';
import uploadRoutes from './routes/upload.js';
import apiRoutes, { setIoInstance } from './routes/api.js';
import filesRoutes from './routes/files.js';
import { setPollerIo, startAllWatchers } from './services/web-poller.js';
import { setupTerminalWebSocket, CLAUDE_HTML, OPENCODE_HTML } from './terminal.js';
import type { ClientToServerEvents, ServerToClientEvents } from '../../shared/types.js';

export async function main() {
  await initDatabase();

  const app = express();
  const server = createServer(app);

  // Raw HTTP-level request log — fires before Express, before any middleware.
  // If this appears but [Upload] doesn't, something in Express middleware is blocking.
  // If this doesn't appear at all, the request never reaches Node.js.
  server.on('request', (req) => {
    if (req.url?.startsWith('/upload')) {
      console.log(
        `[RAW] ${req.method} ${req.url}` +
        `  ct: ${(req.headers['content-type'] ?? '').slice(0, 60)}` +
        `  cl: ${req.headers['content-length'] ?? 'chunked'}`
      );
    }
  });

  // Terminal WebSocket must be set up BEFORE Socket.IO to ensure its upgrade
  // handler runs first (Socket.IO destroys non-matching upgrade sockets).
  setupTerminalWebSocket(server);

  const io = new Server<ClientToServerEvents, ServerToClientEvents>(server, {
    cors: {
      origin: '*',
      methods: ['GET', 'POST'],
    },
    maxHttpBufferSize: Infinity,
  });

  app.set('trust proxy', true);
  app.use(cors());
  app.use(express.json({ limit: '100gb' }));
  app.use(express.urlencoded({ extended: true, limit: '100gb' }));

  // Static files for chat uploads
  const uploadsDir = process.env.MESSENGER_UPLOADS_DIR || path.join(__dirname, '..', 'uploads');
  app.use('/uploads', express.static(uploadsDir));

  // xterm.js served locally for offline use
  const publicDir = process.env.MESSENGER_PUBLIC_DIR || path.join(__dirname, '..', 'public');
  app.use('/xterm', express.static(path.join(publicDir, 'xterm')));

  // API Routes
  app.use('/auth', authRoutes);
  app.use('/rooms', roomRoutes);

  // Upload request logger — fires before multer touches anything
  app.use('/upload', (req: express.Request, _res: express.Response, next: express.NextFunction) => {
    console.log(
      `[Upload] ${req.method} ${req.path}` +
      `  content-type: ${req.headers['content-type']?.slice(0, 60)}` +
      `  content-length: ${req.headers['content-length'] ?? 'chunked'}`
    );
    next();
  });
  app.use('/upload', uploadRoutes);
  app.use('/api', apiRoutes);
  app.use('/files', filesRoutes);

  // Global error handler — always return JSON so the client can show the message
  app.use((err: any, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    console.error('[Server error]', err?.message || err);
    res.status(err?.status || 500).json({ error: err?.message || 'Internal server error' });
  });

  // Health check
  app.get('/health', (_req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  // Claude Code Terminal: /claude
  app.get('/claude', (_req, res) => { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.send(CLAUDE_HTML); });
  app.get('/claude/', (_req, res) => { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.send(CLAUDE_HTML); });

  // OpenCode Terminal: /opencode
  app.get('/opencode', (_req, res) => { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.send(OPENCODE_HTML); });
  app.get('/opencode/', (_req, res) => { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.send(OPENCODE_HTML); });

  // Serve the web client
  const clientDistPath = process.env.MESSENGER_WEB_DIR || path.join(__dirname, '..', '..', 'client', 'dist-web');
  if (fs.existsSync(clientDistPath)) {
    app.use(express.static(clientDistPath));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(clientDistPath, 'index.html'));
    });
  }

  // Socket.IO
  setupSocketHandlers(io);
  setIoInstance(io);
  setRoomsIo(io);
  setPollerIo(io);

  // Start web watchers and cleanup cron
  startAllWatchers();
  startCleanupCron();

  const PORT = Number(process.env.PORT) || 3000;

  // Disable all Node.js HTTP server timeouts so large uploads never get cut off
  server.setTimeout(0);
  server.requestTimeout = 0;
  server.headersTimeout = 0;
  server.keepAliveTimeout = 0;

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`Messenger Server running on port ${PORT}`);
    console.log(`  Local:   http://localhost:${PORT}`);
    console.log(`  Network: http://0.0.0.0:${PORT}`);
  });
}

// Auto-start when run directly (not when required by Electron)
if (!process.env.MESSENGER_EMBEDDED) {
  main().catch(console.error);
}
