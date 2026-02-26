import { Request, Response, NextFunction } from 'express';
import { queryOne, run } from '../db/index.js';

/**
 * Optional API-key middleware.
 * If a valid `x-api-key` header is present, attaches the owning user to `req.apiUser`.
 * If the header is absent or invalid the request still proceeds (non-blocking).
 */
export function apiKeyAuth(req: Request, _res: Response, next: NextFunction) {
  const apiKey = req.headers['x-api-key'] as string | undefined;
  if (!apiKey) { next(); return; }

  const keyRow = queryOne(
    'SELECT * FROM api_keys WHERE key = ? AND is_active = 1',
    [apiKey],
  );
  if (!keyRow) { next(); return; }

  const user = queryOne('SELECT * FROM users WHERE id = ?', [keyRow.user_id]);
  if (user) {
    (req as any).apiUser = user;
    run("UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?", [keyRow.id]);
  }

  next();
}

/**
 * Strict variant – returns 401 when no valid key is provided.
 */
export function requireApiKey(req: Request, res: Response, next: NextFunction) {
  const apiKey = req.headers['x-api-key'] as string | undefined;
  if (!apiKey) {
    res.status(401).json({ error: 'x-api-key header is required.' });
    return;
  }

  const keyRow = queryOne(
    'SELECT * FROM api_keys WHERE key = ? AND is_active = 1',
    [apiKey],
  );
  if (!keyRow) {
    res.status(401).json({ error: 'Invalid or inactive API key.' });
    return;
  }

  const user = queryOne('SELECT * FROM users WHERE id = ?', [keyRow.user_id]);
  if (!user) {
    res.status(401).json({ error: 'API key user not found.' });
    return;
  }

  (req as any).apiUser = user;
  run("UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?", [keyRow.id]);
  next();
}
