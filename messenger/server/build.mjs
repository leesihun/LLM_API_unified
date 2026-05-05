import { build } from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.join(__dirname, 'dist');

// Clean dist
if (fs.existsSync(distDir)) {
  fs.rmSync(distDir, { recursive: true });
}
fs.mkdirSync(distDir, { recursive: true });

console.log('[BUILD] Bundling server with esbuild...');

await build({
  entryPoints: [path.join(__dirname, 'src', 'index.ts')],
  bundle: true,
  platform: 'node',
  target: 'node18',
  outfile: path.join(distDir, 'server.cjs'),
  format: 'cjs',
  sourcemap: false,
  minify: false,
  // sql.js wasm file must be loaded from disk at runtime
  external: [],
  loader: {
    '.wasm': 'file',
  },
});

// Copy sql.js wasm file
const sqlJsWasmSrc = path.join(__dirname, 'node_modules', 'sql.js', 'dist', 'sql-wasm.wasm');
if (fs.existsSync(sqlJsWasmSrc)) {
  fs.copyFileSync(sqlJsWasmSrc, path.join(distDir, 'sql-wasm.wasm'));
  console.log('[BUILD] Copied sql-wasm.wasm');
}

// Copy public/ (xterm static files) into dist/public/
function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(srcPath, destPath);
    else fs.copyFileSync(srcPath, destPath);
  }
}
const publicSrc = path.join(__dirname, 'public');
if (fs.existsSync(publicSrc)) {
  copyDir(publicSrc, path.join(distDir, 'public'));
  console.log('[BUILD] Copied public/');
}

console.log('[BUILD] Bundle complete: dist/server.cjs');
console.log('[BUILD] Run with: node dist/server.cjs');
console.log('[BUILD] Done!');
