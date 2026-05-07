import cp from 'child_process';
import path from 'path';

const SERVER_DIR = path.join(__dirname, '..');
const MESSENGER_ROOT = path.join(__dirname, '..', '..');
const CONFIG_PATH = path.join(MESSENGER_ROOT, 'config.py');

function findPython(): string | null {
  const candidates = process.platform === 'win32'
    ? ['python', 'py']
    : ['python3', 'python'];

  for (const candidate of candidates) {
    try {
      cp.execFileSync(candidate, ['--version'], { stdio: 'ignore', timeout: 3000 });
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return null;
}

function loadPythonConfig(): Record<string, string> {
  const python = findPython();
  if (!python) {
    console.warn('[config] Python not found; Messenger will use process.env and defaults only.');
    return {};
  }

  try {
    const args = python === 'py'
      ? ['-3', CONFIG_PATH, '--json']
      : [CONFIG_PATH, '--json'];
    const raw = cp.execFileSync(python, args, {
      cwd: MESSENGER_ROOT,
      encoding: 'utf-8',
      timeout: 5000,
      env: process.env,
    });
    return JSON.parse(raw) as Record<string, string>;
  } catch (error) {
    console.warn('[config] Failed to load messenger/config.py:', error);
    return {};
  }
}

export const resolvedMessengerEnv: Record<string, string> = loadPythonConfig();

for (const [key, value] of Object.entries(resolvedMessengerEnv)) {
  if (process.env[key] === undefined && value !== '') {
    process.env[key] = value;
  }
}

export function getMessengerEnv(key: string, fallback: string): string {
  return process.env[key] || resolvedMessengerEnv[key] || fallback;
}

export function resolveMessengerPath(rawPath: string, fallback: string): string {
  const value = rawPath || fallback;
  if (!value) return value;
  if (path.isAbsolute(value)) return value;
  return path.resolve(MESSENGER_ROOT, value);
}

export { MESSENGER_ROOT, SERVER_DIR };
