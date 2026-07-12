/** /api webhook-management endpoints. */
import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../../db/index.js';
import { resolveSender } from './helpers.js';

const router = Router();

const VALID_WEBHOOK_EVENTS = ['new_message', 'message_edited', 'message_deleted', 'message_read'];

router.post('/webhooks', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required (x-api-key, senderId, or senderName).' });
    return;
  }

  const { url, roomId = null, events = ['new_message'], secret = null } = req.body;
  if (!url) {
    res.status(400).json({ error: 'url is required.' });
    return;
  }
  if (!Array.isArray(events) || events.length === 0) {
    res.status(400).json({ error: 'events must be a non-empty array.' });
    return;
  }
  for (const e of events) {
    if (!VALID_WEBHOOK_EVENTS.includes(e)) {
      res.status(400).json({ error: `Invalid event "${e}". Valid: ${VALID_WEBHOOK_EVENTS.join(', ')}` });
      return;
    }
  }

  const result = run(
    'INSERT INTO webhooks (url, room_id, events, secret, created_by) VALUES (?, ?, ?, ?, ?)',
    [url, roomId, JSON.stringify(events), secret, sender.id],
  );

  res.status(201).json({
    success: true,
    webhook: { id: result.lastInsertRowid, url, roomId, events, isActive: true },
  });
});

router.get('/webhooks', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const webhooks = queryAll(
    'SELECT * FROM webhooks WHERE created_by = ? ORDER BY created_at DESC',
    [sender.id],
  );

  res.json(
    webhooks.map((w: any) => ({
      id: w.id,
      url: w.url,
      roomId: w.room_id,
      events: JSON.parse(w.events),
      isActive: !!w.is_active,
      createdAt: w.created_at,
    })),
  );
});

router.delete('/webhooks/:id', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const wh = queryOne('SELECT created_by FROM webhooks WHERE id = ?', [Number(req.params.id)]);
  if (!wh || wh.created_by !== sender.id) {
    res.status(404).json({ error: 'Webhook not found or does not belong to you.' });
    return;
  }

  run('DELETE FROM webhooks WHERE id = ?', [Number(req.params.id)]);
  res.json({ success: true });
});

router.patch('/webhooks/:id', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const whId = Number(req.params.id);
  const wh = queryOne('SELECT * FROM webhooks WHERE id = ?', [whId]);
  if (!wh || wh.created_by !== sender.id) {
    res.status(404).json({ error: 'Webhook not found or does not belong to you.' });
    return;
  }

  const { url, events, isActive, secret } = req.body;
  if (url !== undefined)      run('UPDATE webhooks SET url = ? WHERE id = ?', [url, whId]);
  if (events !== undefined)   run('UPDATE webhooks SET events = ? WHERE id = ?', [JSON.stringify(events), whId]);
  if (isActive !== undefined) run('UPDATE webhooks SET is_active = ? WHERE id = ?', [isActive ? 1 : 0, whId]);
  if (secret !== undefined)   run('UPDATE webhooks SET secret = ? WHERE id = ?', [secret, whId]);

  const updated = queryOne('SELECT * FROM webhooks WHERE id = ?', [whId]);
  res.json({
    id: updated.id,
    url: updated.url,
    roomId: updated.room_id,
    events: JSON.parse(updated.events),
    isActive: !!updated.is_active,
  });
});

export default router;
