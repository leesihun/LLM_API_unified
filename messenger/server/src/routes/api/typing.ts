/** /api typing-indicator endpoints (used by bots). */
import { Router, Request, Response } from 'express';
import { getIo } from '../../services/io.js';
import { resolveSender } from './helpers.js';

const router = Router();

// Auto-clear typing after this many ms if no stop-typing call arrives
const API_TYPING_TIMEOUT_MS = 15_000;
const apiTypingTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

router.post('/typing', (req: Request, res: Response) => {
  const { roomId, statusText } = req.body;
  if (!roomId) {
    res.status(400).json({ error: 'roomId is required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const io = getIo();
  if (io) {
    const payload: { roomId: number; userId: number; userName: string; statusText?: string } = {
      roomId: Number(roomId),
      userId: sender.id,
      userName: sender.name,
    };
    if (typeof statusText === 'string' && statusText.trim()) {
      payload.statusText = statusText.trim();
    }
    io.to(`room:${roomId}`).emit('user_typing', payload);

    // Auto-clear after timeout (prevents stuck indicators if stop-typing never arrives)
    const timeoutKey = `api:${sender.id}:${roomId}`;
    const existing = apiTypingTimeouts.get(timeoutKey);
    if (existing) clearTimeout(existing);
    apiTypingTimeouts.set(timeoutKey, setTimeout(() => {
      apiTypingTimeouts.delete(timeoutKey);
      getIo()?.to(`room:${roomId}`).emit('user_stop_typing', {
        roomId: Number(roomId),
        userId: sender.id,
      });
    }, API_TYPING_TIMEOUT_MS));
  }

  res.json({ success: true });
});

router.post('/stop-typing', (req: Request, res: Response) => {
  const { roomId } = req.body;
  if (!roomId) {
    res.status(400).json({ error: 'roomId is required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const io = getIo();
  if (io) {
    io.to(`room:${roomId}`).emit('user_stop_typing', {
      roomId: Number(roomId),
      userId: sender.id,
    });

    // Clear any pending auto-timeout
    const timeoutKey = `api:${sender.id}:${roomId}`;
    const existing = apiTypingTimeouts.get(timeoutKey);
    if (existing) {
      clearTimeout(existing);
      apiTypingTimeouts.delete(timeoutKey);
    }
  }

  res.json({ success: true });
});

export default router;
