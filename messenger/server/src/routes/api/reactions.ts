/** /api reaction + pinned-message endpoints. */
import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../../db/index.js';
import { buildMessageData } from '../../db/messages.js';
import { toggleReaction } from '../../services/messages.js';
import { resolveSender } from './helpers.js';

const router = Router();

// POST /api/reactions
router.post('/reactions', (req: Request, res: Response) => {
  const { messageId, emoji } = req.body;
  if (!messageId || !emoji) {
    res.status(400).json({ error: 'messageId and emoji are required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const result = toggleReaction(Number(messageId), sender.id, emoji);
  if (!result) {
    res.status(404).json({ error: 'Message not found.' });
    return;
  }

  res.json({ success: true, reactions: result.reactions });
});

// GET /api/pins/:roomId
router.get('/pins/:roomId', (req: Request, res: Response) => {
  const roomId = Number(req.params.roomId);
  const pins = queryAll(
    `SELECT pm.id as pin_id, pm.room_id, pm.pinned_by, pm.pinned_at, pu.name as pinner_name,
            m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
     FROM pinned_messages pm
     JOIN messages m ON m.id = pm.message_id
     JOIN users u ON u.id = m.sender_id
     JOIN users pu ON pu.id = pm.pinned_by
     WHERE pm.room_id = ?
     ORDER BY pm.pinned_at DESC`,
    [roomId],
  );

  const result = pins.map((p: any) => ({
    id: p.pin_id,
    messageId: p.id,
    roomId: p.room_id,
    pinnedBy: p.pinned_by,
    pinnedByName: p.pinner_name,
    pinnedAt: p.pinned_at,
    message: buildMessageData(p),
  }));

  res.json(result);
});

// POST /api/pins
router.post('/pins', (req: Request, res: Response) => {
  const { messageId, roomId } = req.body;
  if (!messageId || !roomId) {
    res.status(400).json({ error: 'messageId and roomId are required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const existing = queryOne('SELECT id FROM pinned_messages WHERE message_id = ?', [messageId]);
  if (existing) {
    res.status(409).json({ error: 'Message is already pinned.' });
    return;
  }

  run('INSERT INTO pinned_messages (message_id, room_id, pinned_by) VALUES (?, ?, ?)', [messageId, roomId, sender.id]);
  res.status(201).json({ success: true });
});

// DELETE /api/pins/:messageId
router.delete('/pins/:messageId', (req: Request, res: Response) => {
  const messageId = Number(req.params.messageId);
  run('DELETE FROM pinned_messages WHERE message_id = ?', [messageId]);
  res.json({ success: true });
});

export default router;
