import { app, BrowserWindow, Notification, ipcMain, globalShortcut } from 'electron';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Ensure proper DPI-aware rendering on Windows
if (process.platform === 'win32') {
  app.commandLine.appendSwitch('high-dpi-support', '1');
}

// ---------------------------------------------------------------------------
// Thin client — the desktop app is just a window pointed at the master node's
// Messenger server. The web client (services/api.ts) targets window.location
// .origin, so loading the master URL makes axios + Socket.IO + terminals all
// talk to the master with no bundled server.
// ---------------------------------------------------------------------------

function getIconPath(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'icon.png');
  }
  return path.join(__dirname, '..', 'src', 'assets', 'icon.png');
}

// Normalize a user/baked URL: trim, drop trailing slash, and prepend http://
// when no scheme is present. Browsers auto-prepend a scheme but Electron's
// loadURL does not — without this, "10.0.0.5:10006" fails to load.
function normalizeServerUrl(url: string): string {
  let u = (url || '').trim().replace(/\/+$/, '');
  if (u && !/^https?:\/\//i.test(u)) u = 'http://' + u;
  return u;
}

// Per-user config: %APPDATA%/Messenger/config.json holds the chosen server URL.
function getUserConfigPath(): string {
  return path.join(app.getPath('userData'), 'config.json');
}

function readUserServerUrl(): string {
  try {
    const raw = fs.readFileSync(getUserConfigPath(), 'utf-8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.serverUrl === 'string' && parsed.serverUrl.trim()) {
      return normalizeServerUrl(parsed.serverUrl);
    }
  } catch {
    /* not configured yet */
  }
  return '';
}

// Build-time default baked into resources/app-config.json (from cluster_config).
function readBakedServerUrl(): string {
  try {
    const candidate = app.isPackaged
      ? path.join(process.resourcesPath, 'app-config.json')
      : path.join(__dirname, '..', 'app-config.json');
    const raw = fs.readFileSync(candidate, 'utf-8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.serverUrl === 'string' && parsed.serverUrl.trim()) {
      return normalizeServerUrl(parsed.serverUrl);
    }
  } catch {
    /* no baked default */
  }
  return '';
}

function resolveServerUrl(): string {
  return readUserServerUrl() || readBakedServerUrl();
}

function saveUserServerUrl(url: string): void {
  const clean = normalizeServerUrl(url);
  fs.mkdirSync(path.dirname(getUserConfigPath()), { recursive: true });
  fs.writeFileSync(getUserConfigPath(), JSON.stringify({ serverUrl: clean }, null, 2));
}

function getSetupHtmlPath(): string {
  // setup.html is shipped next to the built main.js (dist-electron/).
  return path.join(__dirname, 'setup.html');
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------
let mainWindow: BrowserWindow | null = null;

function loadServer(win: BrowserWindow) {
  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
    return;
  }
  const serverUrl = resolveServerUrl();
  if (!serverUrl) {
    win.loadFile(getSetupHtmlPath());
    return;
  }
  win.loadURL(serverUrl).catch(() => {
    win.loadFile(getSetupHtmlPath(), { query: { error: 'unreachable', url: serverUrl } });
  });
}

function openSetup() {
  if (!mainWindow) return;
  mainWindow.loadFile(getSetupHtmlPath(), { query: { current: resolveServerUrl() } });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // ESM preload (.mjs) only loads when the renderer is not sandboxed.
      sandbox: false,
    },
    icon: getIconPath(),
    title: 'Messenger',
    show: false,
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  // If the master URL is set but the page fails to load, drop back to setup.
  mainWindow.webContents.on('did-fail-load', (_e, errorCode, desc, validatedURL, isMainFrame) => {
    // Only react to top-level navigation failures. did-fail-load also fires for
    // subframes/aborted subresource loads — a page Chrome renders fine can emit
    // those, and bouncing on them traps the user on the setup screen.
    if (!isMainFrame) return;
    // -3 == ERR_ABORTED (redirects, in-app navigation); not a real failure.
    if (errorCode === -3) return;
    if (validatedURL.startsWith('file://')) return;
    console.error(`[main] main-frame load failed: ${errorCode} ${desc} ${validatedURL}`);
    mainWindow?.loadFile(getSetupHtmlPath(), { query: { error: 'unreachable', url: validatedURL } });
  });

  loadServer(mainWindow);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  createWindow();
  // Ctrl+, (Cmd+, on macOS) reopens the server-URL settings page.
  globalShortcut.register('CommandOrControl+,', openSetup);
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------
ipcMain.handle('get-server-url', () => resolveServerUrl());

ipcMain.handle('set-server-url', (_event, url: string) => {
  if (typeof url !== 'string' || !url.trim()) return false;
  saveUserServerUrl(url);
  if (mainWindow) loadServer(mainWindow);
  return true;
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
