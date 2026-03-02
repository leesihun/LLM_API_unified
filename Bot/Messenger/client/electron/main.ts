import { app, BrowserWindow, Notification, ipcMain } from 'electron';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';
import http from 'http';

const _require = createRequire(import.meta.url);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SERVER_PORT = 10006;

function getIconPath(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'icon.png');
  }
  return path.join(__dirname, '..', 'src', 'assets', 'icon.png');
}

// ---------------------------------------------------------------------------
// Embedded server — only when running as a packaged app
// ---------------------------------------------------------------------------
function getAppDataDir(): string {
  return path.join(app.getPath('userData'), 'messenger-data');
}

function startEmbeddedServer(): Promise<void> {
  const appData = getAppDataDir();

  // Ensure writable directories exist
  for (const sub of ['data', 'uploads', 'chunks', 'storage']) {
    fs.mkdirSync(path.join(appData, sub), { recursive: true });
  }

  // Set env vars so the server uses our writable directories
  process.env.MESSENGER_EMBEDDED = '1';
  process.env.PORT = String(SERVER_PORT);
  process.env.MESSENGER_DATA_DIR = path.join(appData, 'data');
  process.env.MESSENGER_UPLOADS_DIR = path.join(appData, 'uploads');
  process.env.MESSENGER_CHUNKS_DIR = path.join(appData, 'chunks');
  process.env.MESSENGER_STORAGE_DIR = path.join(appData, 'storage');

  // Static resources shipped with the app
  const resPath = process.resourcesPath;
  process.env.MESSENGER_PUBLIC_DIR = path.join(resPath, 'server-public');
  process.env.MESSENGER_WEB_DIR = path.join(resPath, 'web');

  // Load and start the bundled server
  const serverPath = path.join(resPath, 'server', 'server.cjs');
  const serverModule = _require(serverPath);
  return serverModule.main();
}

function waitForServer(port: number, timeoutMs = 15000): Promise<void> {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    function check() {
      const req = http.get(`http://localhost:${port}/health`, (res) => {
        if (res.statusCode === 200) return resolve();
        retry();
      });
      req.on('error', retry);
      req.setTimeout(1000, () => { req.destroy(); retry(); });
    }
    function retry() {
      if (Date.now() - start > timeoutMs) return reject(new Error('Server start timeout'));
      setTimeout(check, 200);
    }
    check();
  });
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------
let mainWindow: BrowserWindow | null = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: getIconPath(),
    title: 'Messenger',
    show: false,
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else if (app.isPackaged) {
    // In packaged mode, load from the embedded server
    mainWindow.loadURL(`http://localhost:${SERVER_PORT}`);
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  if (app.isPackaged) {
    try {
      await startEmbeddedServer();
      await waitForServer(SERVER_PORT);
    } catch (err) {
      console.error('Failed to start embedded server:', err);
    }
  }
  createWindow();
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// IPC: Show desktop notification
ipcMain.handle('show-notification', (_event, { title, body }: { title: string; body: string }) => {
  if (Notification.isSupported()) {
    const notification = new Notification({ title, body });
    notification.on('click', () => {
      mainWindow?.show();
      mainWindow?.focus();
    });
    notification.show();
  }
});

// IPC: Flash taskbar
ipcMain.handle('flash-window', () => {
  mainWindow?.flashFrame(true);
});
