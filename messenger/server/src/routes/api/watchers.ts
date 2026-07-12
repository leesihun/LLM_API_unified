/** /api web-watcher management endpoints. */
import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../../db/index.js';
import { startWatcher, stopWatcher } from '../../services/web-poller.js';
import { resolveSender, isRoomMember } from './helpers.js';

const router = Router();

router.post('/watchers', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const { url, roomId, intervalSeconds = 10 } = req.body;
  if (!url || !roomId) {
    res.status(400).json({ error: 'url and roomId are required.' });
    return;
  }

  const room = queryOne('SELECT 1 FROM rooms WHERE id = ?', [roomId]);
  if (!room) {
    res.status(404).json({ error: 'Room not found.' });
    return;
  }

  if (!isRoomMember(roomId, sender.id)) {
    res.status(403).json({ error: 'Sender is not a member of this room.' });
    return;
  }

  const interval = Math.max(5, Math.min(3600, Number(intervalSeconds)));
  const result = run(
    'INSERT INTO web_watchers (url, room_id, sender_id, interval_seconds) VALUES (?, ?, ?, ?)',
    [url, roomId, sender.id, interval],
  );

  const watcherId = result.lastInsertRowid;
  startWatcher(watcherId, interval);

  res.status(201).json({
    success: true,
    watcher: { id: watcherId, url, roomId, intervalSeconds: interval, isActive: true },
  });
});

router.get('/watchers', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const watchers = queryAll(
    'SELECT * FROM web_watchers WHERE sender_id = ? ORDER BY created_at DESC',
    [sender.id],
  );

  res.json(
    watchers.map((w: any) => ({
      id: w.id,
      url: w.url,
      roomId: w.room_id,
      intervalSeconds: w.interval_seconds,
      isActive: !!w.is_active,
      lastCheckedAt: w.last_checked_at,
      lastChangedAt: w.last_changed_at,
      createdAt: w.created_at,
    })),
  );
});

router.delete('/watchers/:id', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const watcherId = Number(req.params.id);
  const w = queryOne('SELECT sender_id FROM web_watchers WHERE id = ?', [watcherId]);
  if (!w || w.sender_id !== sender.id) {
    res.status(404).json({ error: 'Watcher not found or does not belong to you.' });
    return;
  }

  stopWatcher(watcherId);
  run('DELETE FROM web_watchers WHERE id = ?', [watcherId]);
  res.json({ success: true });
});

router.patch('/watchers/:id', (req: Request, res: Response) => {
  const sender = resolveSender(req);
  if (!sender) {
    res.status(401).json({ error: 'Authentication required.' });
    return;
  }

  const watcherId = Number(req.params.id);
  const w = queryOne('SELECT * FROM web_watchers WHERE id = ?', [watcherId]);
  if (!w || w.sender_id !== sender.id) {
    res.status(404).json({ error: 'Watcher not found or does not belong to you.' });
    return;
  }

  const { isActive, intervalSeconds, url } = req.body;

  if (url !== undefined) {
    run('UPDATE web_watchers SET url = ? WHERE id = ?', [url, watcherId]);
  }

  if (intervalSeconds !== undefined) {
    const interval = Math.max(5, Math.min(3600, Number(intervalSeconds)));
    run('UPDATE web_watchers SET interval_seconds = ? WHERE id = ?', [interval, watcherId]);
    if (w.is_active) {
      stopWatcher(watcherId);
      startWatcher(watcherId, interval);
    }
  }

  if (isActive !== undefined) {
    run('UPDATE web_watchers SET is_active = ? WHERE id = ?', [isActive ? 1 : 0, watcherId]);
    if (isActive) {
      const fresh = queryOne('SELECT interval_seconds FROM web_watchers WHERE id = ?', [watcherId]);
      startWatcher(watcherId, fresh.interval_seconds);
    } else {
      stopWatcher(watcherId);
    }
  }

  const updated = queryOne('SELECT * FROM web_watchers WHERE id = ?', [watcherId]);
  res.json({
    id: updated.id,
    url: updated.url,
    roomId: updated.room_id,
    intervalSeconds: updated.interval_seconds,
    isActive: !!updated.is_active,
    lastCheckedAt: updated.last_checked_at,
    lastChangedAt: updated.last_changed_at,
  });
});

export default router;
