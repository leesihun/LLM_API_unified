/**
 * Build script: produces a single portable Messenger.exe
 *
 * Steps:
 *   1. Build web client (vite build --config vite.config.web.ts)
 *   2. Bundle server with esbuild → portable-staging/server/server.cjs
 *   3. Copy static resources into portable-staging/
 *   4. Build Electron main + preload (vite build)
 *   5. Package with electron-builder --win portable
 */

import { build } from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STAGING = path.join(__dirname, 'portable-staging');

function run(cmd, opts = {}) {
  console.log(`\n[RUN] ${cmd}`);
  execSync(cmd, { stdio: 'inherit', ...opts });
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(srcPath, destPath);
    else fs.copyFileSync(srcPath, destPath);
  }
}

// ---- Clean staging ----
if (fs.existsSync(STAGING)) fs.rmSync(STAGING, { recursive: true });
fs.mkdirSync(STAGING, { recursive: true });

// ---- 1. Build web client ----
console.log('\n=== Building web client ===');
run('npx vite build --config vite.config.web.ts', { cwd: path.join(__dirname, 'client') });

// ---- 2. Bundle server with esbuild ----
console.log('\n=== Bundling server ===');
const serverOutDir = path.join(STAGING, 'server');
fs.mkdirSync(serverOutDir, { recursive: true });

await build({
  entryPoints: [path.join(__dirname, 'server', 'src', 'index.ts')],
  bundle: true,
  platform: 'node',
  target: 'node18',
  outfile: path.join(serverOutDir, 'server.cjs'),
  format: 'cjs',
  sourcemap: false,
  minify: false,
  // node-pty is optional native module — keep external so it's loaded at runtime
  // ws is used for WebSocket terminal — also native-ish
  external: ['node-pty'],
  loader: { '.wasm': 'file' },
});

// Copy sql.js WASM — check both local and hoisted node_modules
const wasmCandidates = [
  path.join(__dirname, 'server', 'node_modules', 'sql.js', 'dist', 'sql-wasm.wasm'),
  path.join(__dirname, 'node_modules', 'sql.js', 'dist', 'sql-wasm.wasm'),
];
const sqlWasmSrc = wasmCandidates.find(p => fs.existsSync(p));
if (sqlWasmSrc) {
  fs.copyFileSync(sqlWasmSrc, path.join(serverOutDir, 'sql-wasm.wasm'));
  console.log('[BUILD] Copied sql-wasm.wasm');
} else {
  console.warn('[BUILD] WARNING: sql-wasm.wasm not found! Database will fail.');
}

// ---- 3. Copy static resources ----
console.log('\n=== Copying static resources ===');

// Web client dist → staging/web/
const webDist = path.join(__dirname, 'client', 'dist-web');
if (fs.existsSync(webDist)) {
  copyDir(webDist, path.join(STAGING, 'web'));
  console.log('[BUILD] Copied web client dist');
}

// Server public/ (xterm) → staging/server-public/
const serverPublic = path.join(__dirname, 'server', 'public');
if (fs.existsSync(serverPublic)) {
  copyDir(serverPublic, path.join(STAGING, 'server-public'));
  console.log('[BUILD] Copied server public/');
}

// Icon
const iconSrc = path.join(__dirname, 'client', 'src', 'assets', 'icon.png');
if (fs.existsSync(iconSrc)) {
  fs.copyFileSync(iconSrc, path.join(STAGING, 'icon.png'));
  console.log('[BUILD] Copied icon.png');
}

// ---- 4. Build Electron (main + preload via vite) ----
console.log('\n=== Building Electron main + preload ===');
run('npx vite build', { cwd: path.join(__dirname, 'client') });

// ---- 5. Package with electron-builder ----
console.log('\n=== Packaging portable .exe ===');
run('npx electron-builder --win portable --config electron-builder-portable.json', {
  cwd: path.join(__dirname, 'client'),
});

console.log('\n=== Build complete! ===');
console.log('Output: client/dist-portable/');
