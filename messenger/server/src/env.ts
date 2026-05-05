import fs from 'fs';
import path from 'path';

export function loadEnvFile(filePath: string): Record<string, string> {
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
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1);
      }
      result[key] = val;
    }
    return result;
  } catch {
    return {};
  }
}

const SERVER_DIR = path.join(__dirname, '..');
const MESSENGER_ROOT = path.join(__dirname, '..', '..');
const LEGACY_SERVER_ENV_PATH = path.join(SERVER_DIR, '.env');
const MESSENGER_ENV_PATH = path.join(MESSENGER_ROOT, '.env');

const legacyServerEnv = loadEnvFile(LEGACY_SERVER_ENV_PATH);
const messengerEnv = loadEnvFile(MESSENGER_ENV_PATH);

export const resolvedMessengerEnv: Record<string, string> = {
  ...legacyServerEnv,
  ...messengerEnv,
};

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
