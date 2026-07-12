/** /api bot registration + API-key management endpoints. */
import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { queryOne, run } from '../../db/index.js';
import { generateApiKey } from './helpers.js';

const router = Router();

// POST /api/bots  – Register a new bot user and receive an API key
router.post('/bots', (req: Request, res: Response) => {
  const { name } = req.body;
  if (!name || typeof name !== 'string' || name.trim().length === 0) {
    res.status(400).json({ error: 'name is required.' });
    return;
  }

  const trimmedName = name.trim();
  if (trimmedName.length > 50) {
    res.status(400).json({ error: 'Name must be 50 characters or fewer.' });
    return;
  }

  const existing = queryOne('SELECT * FROM users WHERE name = ?', [trimmedName]);
  if (existing) {
    if (!existing.is_bot) {
      res.status(409).json({ error: 'A non-bot user with this name already exists.' });
      return;
    }
    const newKey = generateApiKey();
    run('INSERT INTO api_keys (user_id, key, label) VALUES (?, ?, ?)', [
      existing.id, newKey, `${trimmedName} re-registered key`,
    ]);
    res.status(200).json({
      bot: { id: existing.id, name: existing.name, isBot: true, createdAt: existing.created_at },
      apiKey: newKey,
    });
    return;
  }

  const botIp = `bot:${uuidv4()}`;
  run('INSERT INTO users (ip, name, is_bot) VALUES (?, ?, 1)', [botIp, trimmedName]);

  const bot = queryOne('SELECT * FROM users WHERE ip = ?', [botIp]);
  const apiKey = generateApiKey();
  run('INSERT INTO api_keys (user_id, key, label) VALUES (?, ?, ?)', [
    bot.id, apiKey, `${trimmedName} default key`,
  ]);

  res.status(201).json({
    bot: { id: bot.id, name: bot.name, isBot: true, createdAt: bot.created_at },
    apiKey,
  });
});

// GET /api/bots/me  – Identify the bot behind the current API key
router.get('/bots/me', (req: Request, res: Response) => {
  const user = (req as any).apiUser;
  if (!user) {
    res.status(401).json({ error: 'Valid x-api-key header is required.' });
    return;
  }
  res.json({ id: user.id, name: user.name, isBot: !!user.is_bot, createdAt: user.created_at });
});

// POST /api/bots/keys  – Generate an additional API key (requires existing key)
router.post('/bots/keys', (req: Request, res: Response) => {
  const user = (req as any).apiUser;
  if (!user) {
    res.status(401).json({ error: 'Valid x-api-key header is required.' });
    return;
  }

  const label = req.body.label || 'additional key';
  const apiKey = generateApiKey();
  run('INSERT INTO api_keys (user_id, key, label) VALUES (?, ?, ?)', [user.id, apiKey, label]);

  res.status(201).json({ apiKey, label });
});

// DELETE /api/bots/keys/:key  – Revoke an API key
router.delete('/bots/keys/:key', (req: Request, res: Response) => {
  const user = (req as any).apiUser;
  if (!user) {
    res.status(401).json({ error: 'Valid x-api-key header is required.' });
    return;
  }

  const keyToRevoke = req.params.key;
  const keyRow = queryOne('SELECT id, user_id FROM api_keys WHERE key = ?', [keyToRevoke]);
  if (!keyRow || keyRow.user_id !== user.id) {
    res.status(404).json({ error: 'Key not found or does not belong to you.' });
    return;
  }

  run('DELETE FROM api_keys WHERE id = ?', [keyRow.id]);
  res.json({ success: true });
});

export default router;
