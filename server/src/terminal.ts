import * as http from 'http';
import * as path from 'path';
import * as fs from 'fs';
import * as cp from 'child_process';
import { WebSocketServer, WebSocket } from 'ws';

let pty: typeof import('node-pty') | null = null;
try {
  pty = require('node-pty');
} catch {
  console.warn('[terminal] node-pty not available — terminal features disabled');
}

// ---------------------------------------------------------------------------
// .env parser (no dotenv dependency needed)
// ---------------------------------------------------------------------------
function loadEnvFile(filePath: string): Record<string, string> {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    const result: Record<string, string> = {};
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx < 0) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      let val = trimmed.slice(eqIdx + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) ||
          (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      result[key] = val;
    }
    return result;
  } catch {
    return {};
  }
}

// Config priority: process.env > Messenger/server/.env > ClaudeCodeWrapper/.env > default
// __dirname = .../Messenger/server/src
const SERVER_ENV_PATH  = path.join(__dirname, '..', '.env');
const WRAPPER_ENV_PATH = path.join(__dirname, '..', '..', '..', 'ClaudeCodeWrapper', '.env');

const serverEnv  = loadEnvFile(SERVER_ENV_PATH);
const wrapperEnv = loadEnvFile(WRAPPER_ENV_PATH);

function getConfig(key: string, fallback: string): string {
  return process.env[key] || serverEnv[key] || wrapperEnv[key] || fallback;
}

export const SECRET_TOKEN = getConfig('SECRET_TOKEN', 'leesihun');
export const WORKSPACE_DIR = getConfig('WORKSPACE_DIR', process.cwd());
const CLAUDE_CMD    = getConfig('CLAUDE_CMD', 'claude');
const OPENCODE_CMD  = getConfig('OPENCODE_CMD', 'opencode');

// ---------------------------------------------------------------------------
// Resolve an executable robustly across install methods (npm, volta, scoop…)
// ---------------------------------------------------------------------------
interface SpawnTarget { cmd: string; args: string[]; }

function resolveExecutable(cmdName: string): SpawnTarget {
  const isWin = process.platform === 'win32';

  // 1. Absolute path that already exists
  if (path.isAbsolute(cmdName) && fs.existsSync(cmdName)) {
    return isWin
      ? { cmd: 'cmd.exe', args: ['/c', cmdName] }
      : { cmd: cmdName, args: [] };
  }

  // 2. where.exe / which
  try {
    const finder = isWin ? 'where.exe' : 'which';
    const raw = cp.execFileSync(finder, [cmdName], { encoding: 'utf-8', timeout: 3000 });
    const lines = raw.trim().split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const found = isWin ? (lines.find((l) => l.endsWith('.cmd')) || lines[0]) : lines[0];
    if (found) {
      return isWin
        ? { cmd: 'cmd.exe', args: ['/c', found] }
        : { cmd: found, args: [] };
    }
  } catch { /* not on PATH */ }

  // 3. Common install locations
  const home = process.env.USERPROFILE || process.env.HOME || '';
  const candidates = isWin ? [
    path.join(home, 'AppData', 'Roaming', 'npm', `${cmdName}.cmd`),
    path.join(home, '.volta', 'bin', `${cmdName}.cmd`),
    path.join(home, 'scoop', 'shims', `${cmdName}.cmd`),
    `C:\\Program Files\\nodejs\\${cmdName}.cmd`,
  ] : [
    path.join(home, '.volta', 'bin', cmdName),
    path.join(home, '.nvm', 'current', 'bin', cmdName),
    `/usr/local/bin/${cmdName}`,
    `/opt/homebrew/bin/${cmdName}`,
    `/usr/bin/${cmdName}`,
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return isWin
        ? { cmd: 'cmd.exe', args: ['/c', candidate] }
        : { cmd: candidate, args: [] };
    }
  }

  // 4. Last resort: let the shell resolve
  console.warn(`[terminal] Could not resolve '${cmdName}' — falling back to shell resolution`);
  return isWin
    ? { cmd: 'cmd.exe', args: ['/c', cmdName] }
    : { cmd: cmdName, args: [] };
}

const CLAUDE_SPAWN   = resolveExecutable(CLAUDE_CMD);
const OPENCODE_SPAWN = resolveExecutable(OPENCODE_CMD);

console.log(`[terminal] Claude   spawn: ${CLAUDE_SPAWN.cmd} ${CLAUDE_SPAWN.args.join(' ')}`);
console.log(`[terminal] OpenCode spawn: ${OPENCODE_SPAWN.cmd} ${OPENCODE_SPAWN.args.join(' ')}`);
console.log(`[terminal] Workspace:      ${WORKSPACE_DIR}`);

// ---------------------------------------------------------------------------
// Workspace listing
// ---------------------------------------------------------------------------
function listWorkspaces(): string[] {
  try {
    return fs
      .readdirSync(WORKSPACE_DIR)
      .filter((name) => fs.statSync(path.join(WORKSPACE_DIR, name)).isDirectory())
      .sort();
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// HTML factory — parameterised per tool
// ---------------------------------------------------------------------------
interface ToolConfig {
  title: string;
  subtitle: string;
  accentColor: string;
  accentHover: string;
  storageKey: string;  // localStorage key for token
  wsPath: string;      // e.g. '/claude/ws'
}

function makeTerminalHTML(cfg: ToolConfig): string {
  return `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <title>${cfg.title}</title>
  <link rel="stylesheet" href="/xterm/xterm.css" />
  <script src="/xterm/xterm.js"></script>
  <script src="/xterm/addon-fit.js"></script>
  <style>
    :root {
      --bg: #0a0a0a; --surface: #131313; --border: #262626;
      --text: #e5e5e5; --dim: #777;
      --accent: ${cfg.accentColor}; --accent-h: ${cfg.accentHover};
      --ok: #22c55e; --err: #ef4444;
    }
    *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
    html, body { height:100%; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; overflow:hidden; }

    #login { display:flex; align-items:center; justify-content:center; height:100%; }
    .login-card {
      background:var(--surface); border:1px solid var(--border);
      border-radius:16px; padding:40px 32px; width:100%; max-width:380px; text-align:center;
    }
    .login-card h1 { font-size:22px; margin-bottom:6px; }
    .login-card p { color:var(--dim); margin-bottom:24px; font-size:14px; }
    .login-card input {
      width:100%; padding:12px 14px; background:#1c1c1c; border:1px solid var(--border);
      border-radius:10px; color:var(--text); font-size:16px; outline:none; margin-bottom:14px;
    }
    .login-card input:focus { border-color:var(--accent); }
    .login-card button {
      width:100%; padding:12px; background:var(--accent); color:#fff;
      border:none; border-radius:10px; font-size:15px; font-weight:600; cursor:pointer;
    }
    .login-card button:hover { background:var(--accent-h); }
    #login-err { color:var(--err); margin-top:10px; font-size:13px; min-height:18px; }

    #app { display:none; flex-direction:column; height:100%; }
    header {
      display:flex; align-items:center; justify-content:space-between;
      padding:8px 14px; background:var(--surface); border-bottom:1px solid var(--border);
      flex-shrink:0; gap:10px;
    }
    header h1 { font-size:14px; font-weight:700; white-space:nowrap; }
    .conn { display:flex; align-items:center; gap:6px; font-size:13px; color:var(--dim); flex-shrink:0; }
    .dot { width:8px; height:8px; border-radius:50%; background:var(--err); }
    .dot.on { background:var(--ok); }
    #wsSel {
      padding:4px 8px; background:#1c1c1c; border:1px solid var(--border);
      border-radius:8px; color:var(--text); font-size:13px; outline:none; cursor:pointer; max-width:200px;
    }
    #wsSel:focus { border-color:var(--accent); }
    #newSessionBtn {
      padding:4px 12px; background:var(--accent); color:#fff; border:none;
      border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; flex-shrink:0;
    }
    #newSessionBtn:hover { background:var(--accent-h); }
    #newSessionBtn:disabled { opacity:.4; cursor:not-allowed; }
    #term-wrap { flex:1; overflow:hidden; padding:4px; background:#000; }
    #terminal { width:100%; height:100%; }
    .xterm { height:100%; }
    .xterm-viewport { overflow-y:auto !important; }
    #overlay {
      display:none; position:absolute; inset:0;
      background:rgba(0,0,0,.6); align-items:center; justify-content:center; z-index:10;
    }
    #overlay.show { display:flex; }
    .overlay-card {
      background:var(--surface); border:1px solid var(--border); border-radius:14px;
      padding:32px 28px; text-align:center; max-width:360px; width:100%;
    }
    .overlay-card p { color:var(--dim); margin-bottom:20px; font-size:14px; }
    .overlay-card button {
      padding:10px 24px; background:var(--accent); color:#fff; border:none;
      border-radius:8px; font-size:14px; font-weight:600; cursor:pointer;
    }
    .overlay-card button:hover { background:var(--accent-h); }
  </style>
</head>
<body>

<div id="login">
  <div class="login-card">
    <h1>${cfg.title}</h1>
    <p>${cfg.subtitle}</p>
    <input type="password" id="tokenIn" placeholder="Access token" autocomplete="off" />
    <button id="loginBtn">Connect</button>
    <p id="login-err"></p>
  </div>
</div>

<div id="app">
  <header>
    <h1>${cfg.title}</h1>
    <select id="wsSel" title="Workspace"></select>
    <button id="newSessionBtn">New Session</button>
    <div class="conn">
      <span class="dot" id="dot"></span>
      <span id="connTxt">연결 중…</span>
    </div>
  </header>
  <div id="term-wrap"><div id="terminal"></div></div>
</div>

<div id="overlay">
  <div class="overlay-card">
    <h2 style="margin-bottom:10px;">세션 종료</h2>
    <p id="overlay-msg">프로세스가 종료되었습니다.</p>
    <button id="restartBtn">새 세션 시작</button>
  </div>
</div>

<script>
const STORAGE_KEY = '${cfg.storageKey}';
const WS_PATH = '${cfg.wsPath}';

let ws = null, authed = false, sessionActive = false, wasSessionActive = false;
let token = localStorage.getItem(STORAGE_KEY) || '';
let reconnectMs = 1500, reconnectTimer = null;
let term = null, fitAddon = null;
let currentWorkspace = null;

const $login   = document.getElementById('login');
const $app     = document.getElementById('app');
const $dot     = document.getElementById('dot');
const $connTxt = document.getElementById('connTxt');
const $wsSel   = document.getElementById('wsSel');
const $newBtn  = document.getElementById('newSessionBtn');
const $overlay = document.getElementById('overlay');
const $ovMsg   = document.getElementById('overlay-msg');
const $restart = document.getElementById('restartBtn');
const $tokenIn = document.getElementById('tokenIn');
const $loginBtn= document.getElementById('loginBtn');
const $loginErr= document.getElementById('login-err');
const $wrap    = document.getElementById('term-wrap');

function initTerm() {
  if (term) term.dispose();
  term = new Terminal({
    cursorBlink: true, fontSize: 14,
    fontFamily: '"Cascadia Code","Fira Code",Consolas,"Courier New",monospace',
    theme: {
      background: '#000000', foreground: '#e5e5e5', cursor: '#e5e5e5',
      selectionBackground: 'rgba(${cfg.accentColor.replace('#','').match(/../g)?.map(h=>parseInt(h,16)).join(',') ?? '99,102,241'},.35)',
    },
    scrollback: 5000, allowProposedApi: true,
  });
  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById('terminal'));
  setTimeout(() => { try { fitAddon.fit(); } catch(e){} }, 50);
  term.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN && sessionActive)
      ws.send(JSON.stringify({ type: 'input', data }));
  });
}

function connect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + WS_PATH);
  ws.onopen = () => {
    setConn(true); reconnectMs = 1500;
    if (token) ws.send(JSON.stringify({ type: 'auth', token }));
  };
  ws.onclose = () => {
    setConn(false);
    wasSessionActive = sessionActive;
    sessionActive = false;
    if (authed) { reconnectTimer = setTimeout(connect, reconnectMs); reconnectMs = Math.min(reconnectMs * 2, 30000); }
  };
  ws.onerror = () => {};
  ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch(ex){} };
}

function setConn(on) {
  $dot.className = 'dot' + (on ? ' on' : '');
  $connTxt.textContent = on ? '연결됨' : '재연결 중…';
}

function handle(msg) {
  switch (msg.type) {
    case 'auth_ok':
      authed = true;
      localStorage.setItem(STORAGE_KEY, token);
      $loginErr.textContent = '';
      $login.style.display = 'none'; $app.style.display = 'flex';
      populateWorkspaces(msg.workspaces || [], msg.defaultWorkspace);
      if (!term) initTerm();
      if (wasSessionActive) {
        wasSessionActive = false;
        if (term) term.clear();
        ws.send(JSON.stringify({ type: 'reconnect', cols: term?.cols || 120, rows: term?.rows || 40 }));
      } else {
        setTimeout(() => startSession(), 100);
      }
      break;
    case 'session_none':
      // Server has no active session to reattach — start a fresh one.
      setTimeout(() => startSession(), 100);
      break;
    case 'auth_fail':
      $loginErr.textContent = '잘못된 토큰입니다';
      localStorage.removeItem(STORAGE_KEY);
      token = ''; authed = false;
      $login.style.display = 'flex'; $app.style.display = 'none';
      break;
    case 'session_started':
      sessionActive = true; $overlay.classList.remove('show');
      $newBtn.disabled = false; if (term) term.focus();
      break;
    case 'output':
      if (term) term.write(msg.data); break;
    case 'exit':
      sessionActive = false; $overlay.classList.add('show');
      $ovMsg.textContent = '프로세스가 종료되었습니다 (exit code: ' + msg.code + ')';
      break;
    case 'error':
      if (term) term.write('\\r\\n\\x1b[31m[오류] ' + msg.message + '\\x1b[0m\\r\\n'); break;
  }
}

function startSession() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const workspace = $wsSel.value || currentWorkspace || '';
  if (fitAddon && term) { try { fitAddon.fit(); } catch(e){} }
  ws.send(JSON.stringify({ type: 'start', workspace, cols: term?.cols || 120, rows: term?.rows || 40 }));
  $newBtn.disabled = true;
}

function populateWorkspaces(names, defaultPath) {
  $wsSel.innerHTML = '';
  if (!names.length) {
    const opt = document.createElement('option');
    opt.value = ''; opt.textContent = '기본 작업 디렉터리';
    $wsSel.appendChild(opt); return;
  }
  names.forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    if (defaultPath && defaultPath.endsWith(name)) opt.selected = true;
    $wsSel.appendChild(opt);
  });
}

function doLogin() {
  const t = $tokenIn.value.trim(); if (!t) return;
  token = t; localStorage.setItem(STORAGE_KEY, t); $loginErr.textContent = '';
  if (!ws || ws.readyState !== WebSocket.OPEN) connect();
  else ws.send(JSON.stringify({ type: 'auth', token }));
}

const ro = new ResizeObserver(() => {
  if (!term || !fitAddon) return;
  try {
    fitAddon.fit();
    if (ws && ws.readyState === WebSocket.OPEN && sessionActive)
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  } catch(e){}
});
ro.observe($wrap);

$loginBtn.addEventListener('click', doLogin);
$tokenIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
$newBtn.addEventListener('click', () => { if (term) term.clear(); startSession(); });
$restart.addEventListener('click', () => { $overlay.classList.remove('show'); if (term) term.clear(); startSession(); });
$wsSel.addEventListener('change', () => { currentWorkspace = $wsSel.value; });

if (token) { $login.style.display = 'none'; $app.style.display = 'flex'; }
connect();
</script>
</body>
</html>`;
}

// Pre-render HTML pages
export const CLAUDE_HTML = makeTerminalHTML({
  title: 'Claude Code',
  subtitle: 'aihoonbot.com 원격 터미널',
  accentColor: '#6366f1',
  accentHover: '#818cf8',
  storageKey: 'cc_token',
  wsPath: '/claude/ws',
});

export const OPENCODE_HTML = makeTerminalHTML({
  title: 'OpenCode',
  subtitle: 'aihoonbot.com 원격 터미널',
  accentColor: '#10b981',
  accentHover: '#34d399',
  storageKey: 'oc_token',
  wsPath: '/opencode/ws',
});

// ---------------------------------------------------------------------------
// Persistent session — PTY stays alive across WebSocket disconnects.
// Multiple WebSocket clients can attach/detach freely.
// ---------------------------------------------------------------------------
class PersistentSession {
  private ptyProcess: import('node-pty').IPty | null = null;
  private readonly clients: Set<WebSocket> = new Set();
  private outputBuffer = '';
  private readonly MAX_BUFFER = 50_000; // chars of recent output replayed on reconnect

  constructor(private readonly spawnTarget: SpawnTarget) {}

  isRunning(): boolean { return this.ptyProcess !== null; }

  /** Kill any existing PTY and start a fresh one. The requesting WS is added to clients. */
  start(ws: WebSocket, workspace: string, cols: number, rows: number): void {
    if (!pty) {
      this.send(ws, { type: 'error', message: 'node-pty is not installed — terminal unavailable' });
      return;
    }

    this.clients.add(ws);
    if (this.ptyProcess) { try { this.ptyProcess.kill(); } catch {} this.ptyProcess = null; }
    this.outputBuffer = '';

    const cwd = workspace
      ? (workspace.includes(path.sep) || workspace.includes('/')
          ? workspace
          : path.join(WORKSPACE_DIR, workspace))
      : WORKSPACE_DIR;

    try {
      this.ptyProcess = pty.spawn(this.spawnTarget.cmd, this.spawnTarget.args, {
        name: 'xterm-256color',
        cols: cols || 120,
        rows: rows || 40,
        cwd,
        env: { ...process.env, TERM: 'xterm-256color', COLORTERM: 'truecolor' } as NodeJS.ProcessEnv,
      });

      this.ptyProcess.onData((data: string) => {
        this.outputBuffer += data;
        if (this.outputBuffer.length > this.MAX_BUFFER)
          this.outputBuffer = this.outputBuffer.slice(-this.MAX_BUFFER);
        this.broadcast({ type: 'output', data });
      });

      this.ptyProcess.onExit(({ exitCode }: { exitCode: number }) => {
        this.broadcast({ type: 'exit', code: exitCode });
        this.ptyProcess = null;
        this.outputBuffer = '';
      });

      this.broadcast({ type: 'session_started' });
    } catch (err: any) {
      this.send(ws, { type: 'error', message: `PTY 시작 실패: ${err.message}` });
    }
  }

  /**
   * Attach a reconnecting WS to the existing session.
   * Replays buffered output so the client is back in sync.
   * Returns true if a session is running, false if there is nothing to attach to.
   */
  attach(ws: WebSocket, cols?: number, rows?: number): boolean {
    this.clients.add(ws);
    if (this.ptyProcess) {
      if (this.outputBuffer) this.send(ws, { type: 'output', data: this.outputBuffer });
      if (cols && rows) try { this.ptyProcess.resize(cols, rows); } catch {}
      this.send(ws, { type: 'session_started' });
      return true;
    }
    return false;
  }

  /** Detach a WS without killing the PTY. */
  detach(ws: WebSocket): void { this.clients.delete(ws); }

  write(data: string): void { this.ptyProcess?.write(data); }

  resize(cols: number, rows: number): void { try { this.ptyProcess?.resize(cols, rows); } catch {} }

  kill(): void {
    if (this.ptyProcess) { try { this.ptyProcess.kill(); } catch {} this.ptyProcess = null; }
    this.outputBuffer = '';
  }

  private broadcast(msg: object): void {
    const payload = JSON.stringify(msg);
    for (const ws of this.clients)
      if (ws.readyState === WebSocket.OPEN) try { ws.send(payload); } catch {}
  }

  private send(ws: WebSocket, msg: object): void {
    if (ws.readyState === WebSocket.OPEN) try { ws.send(JSON.stringify(msg)); } catch {}
  }
}

// ---------------------------------------------------------------------------
// Generic WebSocket terminal handler factory
// One PersistentSession per tool — survives WebSocket disconnects.
// ---------------------------------------------------------------------------
function attachTerminalWss(
  server: http.Server,
  wsUrlPattern: RegExp,
  spawnTarget: SpawnTarget,
): void {
  const wss = new WebSocketServer({ noServer: true });
  const session = new PersistentSession(spawnTarget); // shared across all connections

  server.on('upgrade', (req, socket, head) => {
    if (wsUrlPattern.test(req.url || '')) {
      wss.handleUpgrade(req, socket as any, head, (ws) => wss.emit('connection', ws, req));
    }
  });

  wss.on('connection', (ws: WebSocket) => {
    let authed = false;

    ws.on('message', (raw: Buffer | string) => {
      let msg: any;
      try { msg = JSON.parse(raw.toString()); } catch { return; }

      switch (msg.type) {
        case 'auth':
          if (msg.token === SECRET_TOKEN) {
            authed = true;
            ws.send(JSON.stringify({
              type: 'auth_ok',
              workspaces: listWorkspaces(),
              defaultWorkspace: WORKSPACE_DIR,
            }));
          } else {
            ws.send(JSON.stringify({ type: 'auth_fail' }));
          }
          break;

        case 'start':
          if (!authed) { ws.send(JSON.stringify({ type: 'error', message: 'Not authenticated' })); break; }
          session.start(ws, msg.workspace || '', Number(msg.cols) || 120, Number(msg.rows) || 40);
          break;

        case 'reconnect':
          // Client requests to reattach to existing session instead of starting a new one.
          if (!authed) { ws.send(JSON.stringify({ type: 'error', message: 'Not authenticated' })); break; }
          if (!session.attach(ws, Number(msg.cols) || undefined, Number(msg.rows) || undefined)) {
            ws.send(JSON.stringify({ type: 'session_none' }));
          }
          break;

        case 'input':
          if (authed && typeof msg.data === 'string') session.write(msg.data);
          break;

        case 'resize':
          if (authed) session.resize(Number(msg.cols) || 80, Number(msg.rows) || 24);
          break;
      }
    });

    // Detach only — PTY keeps running so the next connection can reattach.
    ws.on('close', () => session.detach(ws));
    ws.on('error', () => session.detach(ws));
  });
}

// ---------------------------------------------------------------------------
// Public setup functions — called from index.ts
// ---------------------------------------------------------------------------
export function setupTerminalWebSocket(server: http.Server): void {
  attachTerminalWss(server, /^\/claude\/ws(\?.*)?$/, CLAUDE_SPAWN);
  attachTerminalWss(server, /^\/opencode\/ws(\?.*)?$/, OPENCODE_SPAWN);
}
