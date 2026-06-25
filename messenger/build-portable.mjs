/**
 * Build a single portable, dependency-free Messenger.exe (Windows).
 *
 * The desktop app is a THIN CLIENT: it is just an Electron window pointed at
 * the master node's Messenger server. There is no embedded server, no web
 * bundle, and no native node-pty — the server/web/terminals all live on the
 * master. End users double-click the .exe; no Python/Node/npm required.
 *
 * Steps:
 *   1. Build Electron main + preload (vite build → client/dist-electron/).
 *   2. Copy electron/setup.html → client/dist-electron/ (first-run URL page).
 *   3. Stage app-config.json (default server URL from cluster_config) + icon.
 *   4. Package with electron-builder --win portable.
 *
 * Default server URL comes from cluster_config.MESSENGER_URL; override with:
 *   node build-portable.mjs --master-url http://192.168.0.10:10006
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync, execFileSync } from 'child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT = path.join(__dirname, 'client');
const STAGING = path.join(__dirname, 'portable-staging');
const REPO_ROOT = path.join(__dirname, '..');

function run(cmd, opts = {}) {
  console.log(`\n[RUN] ${cmd}`);
  execSync(cmd, { stdio: 'inherit', ...opts });
}

function resolveMasterUrl() {
  // 1. Explicit CLI override.
  const idx = process.argv.indexOf('--master-url');
  if (idx !== -1 && process.argv[idx + 1]) {
    return process.argv[idx + 1].replace(/\/$/, '');
  }
  // 2. Read cluster_config.MESSENGER_URL via Python (dev-time dependency).
  const python = process.env.PYTHON || 'python';
  try {
    const out = execFileSync(
      python,
      ['-c', 'import cluster_config; print(cluster_config.MESSENGER_URL)'],
      { cwd: REPO_ROOT, encoding: 'utf-8' },
    );
    const url = out.trim();
    if (url) return url.replace(/\/$/, '');
  } catch (err) {
    console.warn('[BUILD] Could not read cluster_config.MESSENGER_URL:', err.message);
  }
  // 3. No default — the app will prompt on first launch.
  return '';
}

// ---- Clean staging ----
if (fs.existsSync(STAGING)) fs.rmSync(STAGING, { recursive: true });
fs.mkdirSync(STAGING, { recursive: true });

// ---- 1. Build Electron main + preload (and the renderer vite emits alongside) ----
console.log('\n=== Building Electron main + preload ===');
run('npx vite build', { cwd: CLIENT });

// ---- 2. Ship the first-run/settings page next to main.js ----
const setupSrc = path.join(CLIENT, 'electron', 'setup.html');
const setupDest = path.join(CLIENT, 'dist-electron', 'setup.html');
fs.copyFileSync(setupSrc, setupDest);
console.log('[BUILD] Copied setup.html → dist-electron/');

// ---- 3. Stage app-config.json + icon ----
const masterUrl = resolveMasterUrl();
fs.writeFileSync(
  path.join(STAGING, 'app-config.json'),
  JSON.stringify({ serverUrl: masterUrl }, null, 2),
);
console.log(`[BUILD] Baked default server URL: ${masterUrl || '(none — prompt on first launch)'}`);

const iconSrc = path.join(CLIENT, 'src', 'assets', 'icon.png');
if (fs.existsSync(iconSrc)) {
  fs.copyFileSync(iconSrc, path.join(STAGING, 'icon.png'));
  console.log('[BUILD] Copied icon.png');
}

// ---- 4. Package with electron-builder ----
console.log('\n=== Packaging portable .exe ===');
run('npx electron-builder --win portable --config electron-builder-portable.json', {
  cwd: CLIENT,
});

console.log('\n=== Build complete! ===');
console.log('Output: client/dist-portable/Messenger.exe');
