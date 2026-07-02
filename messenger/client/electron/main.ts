import { app, BrowserWindow, Menu, Notification, ipcMain } from 'electron';
import path from 'path';
import fs from 'fs';
import os from 'os';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Boot log to a fixed temp path (does NOT need app to be ready) so we can see
// startup crashes that happen before the window/userData logger is available.
function bootLog(...m: unknown[]): void {
  try {
    fs.appendFileSync(
      path.join(os.tmpdir(), 'messenger-boot.log'),
      `[${new Date().toISOString()}] ${m.map((p) => (p instanceof Error ? p.stack || p.message : String(p))).join(' ')}\n`,
    );
  } catch {
    /* ignore */
  }
}
bootLog('main entry; type=', process.type, 'electron=', process.versions.electron, 'node=', process.versions.node);

// If this machine has ELECTRON_RUN_AS_NODE=1 in its environment, Electron runs
// as plain Node: there is no `app`/`BrowserWindow`, the window never appears and
// the process exits immediately — to the user the app "just closes". This env
// var is set system-wide on some machines (and inherited by every launch), so
// we cannot rely on the user removing it. Detect it and relaunch ourselves with
// the variable stripped, as a real Electron app.
if (process.env.ELECTRON_RUN_AS_NODE) {
  bootLog('ELECTRON_RUN_AS_NODE detected -> relaunching as Electron; argv=', JSON.stringify(process.argv));
  try {
    const relaunchEnv = { ...process.env };
    delete relaunchEnv.ELECTRON_RUN_AS_NODE;
    spawn(process.execPath, process.argv.slice(1), {
      env: relaunchEnv,
      detached: true,
      stdio: 'ignore',
    }).unref();
  } catch (e) {
    bootLog('relaunch failed:', e as unknown);
  }
  process.exit(0);
}

// Ensure proper DPI-aware rendering on Windows
try {
  if (process.platform === 'win32') {
    app.commandLine.appendSwitch('high-dpi-support', '1');
  }
} catch (e) {
  bootLog('top-level setup error:', e as unknown);
}

// ---------------------------------------------------------------------------
// File logging — a packaged GUI app has no console, so write a diagnostic log
// to userData/main.log. This is how we find out what actually happens on the
// machines the app runs on (e.g. a renderer/GPU crash that makes the window
// vanish, which looks like "it just closed").
// ---------------------------------------------------------------------------
function logMain(...parts: unknown[]): void {
  const line = `[${new Date().toISOString()}] ${parts.map((p) => (p instanceof Error ? p.stack || p.message : String(p))).join(' ')}\n`;
  try {
    // appendFileSync does not create parent dirs, and Electron only creates
    // userData lazily — without this, every log line before first window
    // creation (including crash handlers) is silently dropped.
    const dir = app.getPath('userData');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'main.log'), line);
  } catch {
    /* userData not ready or not writable */
  }
  try {
    process.stderr.write(line);
  } catch {
    /* no console attached */
  }
}

process.on('uncaughtException', (err) => logMain('uncaughtException:', err));
process.on('unhandledRejection', (reason) => logMain('unhandledRejection:', reason as unknown));
app.on('child-process-gone', (_e, details) =>
  logMain('child-process-gone:', details.type, details.reason, details.exitCode ?? ''),
);

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
    logMain('loadServer: no URL configured -> setup screen');
    win.loadFile(getSetupHtmlPath());
    return;
  }
  logMain('loadServer: loadURL', serverUrl);
  win.loadURL(serverUrl).catch((err) => {
    logMain('loadServer: loadURL rejected', err);
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

  // If the master URL is set but the page fails to load, drop back to setup.
  mainWindow.webContents.on('did-fail-load', (_e, errorCode, desc, validatedURL, isMainFrame) => {
    // Only react to top-level navigation failures. did-fail-load also fires for
    // subframes/aborted subresource loads — a page Chrome renders fine can emit
    // those, and bouncing on them traps the user on the setup screen.
    if (!isMainFrame) return;
    // -3 == ERR_ABORTED (redirects, in-app navigation); not a real failure.
    if (errorCode === -3) return;
    if (validatedURL.startsWith('file://')) return;
    logMain('did-fail-load (main frame):', errorCode, desc, validatedURL);
    mainWindow?.loadFile(getSetupHtmlPath(), { query: { error: 'unreachable', url: validatedURL } });
  });

  mainWindow.webContents.on('did-finish-load', () => {
    logMain('did-finish-load:', mainWindow?.webContents.getURL());
  });

  // A renderer or GPU crash would otherwise leave a blank/closed window that
  // looks like the app "just turned off". Recover to the setup screen and log
  // the reason so we can see why it happened on the user's machine.
  mainWindow.webContents.on('render-process-gone', (_e, details) => {
    logMain('render-process-gone:', details.reason, details.exitCode);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.loadFile(getSetupHtmlPath(), { query: { error: 'crashed', reason: details.reason } });
    }
  });

  mainWindow.webContents.on('unresponsive', () => logMain('renderer unresponsive'));
  mainWindow.webContents.on('preload-error', (_e, p, err) => logMain('preload-error:', p, err));

  loadServer(mainWindow);

  mainWindow.on('closed', () => {
    logMain('main window closed');
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
// File → Server Settings (Ctrl+,) opens the server-URL page. Must be a menu
// accelerator, not globalShortcut: globalShortcut fires system-wide even when
// the app is unfocused, hijacking Ctrl+, from other apps (e.g. VS Code).
function buildMenu(): void {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: 'File',
        submenu: [
          { label: 'Server Settings…', accelerator: 'CmdOrCtrl+,', click: openSetup },
          { type: 'separator' },
          { role: 'quit' },
        ],
      },
      { role: 'editMenu' },
      { role: 'viewMenu' },
    ]),
  );
}

app.whenReady().then(() => {
  logMain('=== app ready === isPackaged=', app.isPackaged, 'userData=', app.getPath('userData'));
  logMain('resolved server URL =', resolveServerUrl() || '(none)');
  buildMenu();
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
