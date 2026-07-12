/** /api room + user endpoints. */
import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../../db/index.js';
import { buildRoomResponse } from '../rooms.js';
import { emitToUser } from '../../socket/handler.js';
import { getIo } from '../../services/io.js';
import { resolveSender, isRoomMember } from './helpers.js';

const router = Router();

// POST /api/leave-room
router.post('/leave-room', (req: Request, res: Response) => {
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

  if (!isRoomMember(roomId, sender.id)) {
    res.status(404).json({ error: 'Not a member of this room.' });
    return;
  }

  run('DELETE FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, sender.id]);

  getIo()?.to(`room:${roomId}`).emit('member_left', { roomId, userId: sender.id, userName: sender.name });

  res.json({ success: true });
});

// GET /api/rooms
router.get('/rooms', (req: Request, res: Response) => {
  const userId = Number(req.query.userId);
  if (!userId) {
    res.status(400).json({ error: 'userId is required.' });
    return;
  }

  const rooms = queryAll(`
    SELECT r.* FROM rooms r
    JOIN room_members rm ON rm.room_id = r.id
    WHERE rm.user_id = ?
    ORDER BY r.created_at DESC
  `, [userId]);

  const result = rooms.map((room: any) => {
    const members = queryAll(`
      SELECT u.id, u.name, u.is_bot FROM users u
      JOIN room_members rm ON rm.user_id = u.id
      WHERE rm.room_id = ?
    `, [room.id]);

    return {
      id: room.id,
      name: room.name,
      isGroup: !!room.is_group,
      createdBy: room.created_by,
      createdAt: room.created_at,
      members: members.map((m: any) => ({ id: m.id, name: m.name, isBot: !!m.is_bot })),
    };
  });

  res.json(result);
});

// POST /api/create-room
router.post('/create-room', (req: Request, res: Response) => {
  const { name, isGroup = true, creatorName, memberNames } = req.body;

  if (!creatorName) {
    res.status(400).json({ error: 'creatorName is required.' });
    return;
  }

  const creator = queryOne('SELECT * FROM users WHERE name = ?', [creatorName]);
  if (!creator) {
    res.status(404).json({ error: 'Creator not found.' });
    return;
  }

  if (!memberNames || !Array.isArray(memberNames) || memberNames.length === 0) {
    res.status(400).json({ error: 'memberNames is required (non-empty array).' });
    return;
  }

  const memberIds: number[] = [creator.id];
  for (const memberName of memberNames) {
    const member = queryOne('SELECT * FROM users WHERE name = ?', [memberName]);
    if (member && member.id !== creator.id) {
      memberIds.push(member.id);
    }
  }

  const roomName = name || (isGroup ? 'Group Chat' : '');
  const result = run('INSERT INTO rooms (name, is_group, created_by) VALUES (?, ?, ?)', [
    roomName,
    isGroup ? 1 : 0,
    creator.id,
  ]);

  const roomId = result.lastInsertRowid;
  for (const memberId of memberIds) {
    run('INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)', [roomId, memberId]);
  }

  const room = buildRoomResponse(Number(roomId), creator.id);
  for (const member of room.members) {
    emitToUser(member.id, 'room_created', room);
  }

  res.status(201).json({ success: true, roomId, name: roomName, members: memberIds });
});

// GET /api/users
router.get('/users', (_req: Request, res: Response) => {
  const users = queryAll('SELECT id, ip, name, is_bot, created_at FROM users ORDER BY name');
  res.json(
    users.map((u: any) => ({
      id: u.id,
      ip: u.ip,
      name: u.name,
      isBot: !!u.is_bot,
      createdAt: u.created_at,
    })),
  );
});

export default router;
