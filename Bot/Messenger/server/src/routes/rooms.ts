import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../db/index.js';
import { buildMessageData, getReactionsForMessage, getReplyTo } from '../db/messages.js';

const router = Router();

let ioInstance: any = null;

export function setRoomsIo(io: any) {
  ioInstance = io;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildRoomResponse(roomId: number, userId: number) {
  const room = queryOne('SELECT * FROM rooms WHERE id = ?', [roomId]);
  const members = queryAll(`
    SELECT u.* FROM users u
    JOIN room_members rm ON rm.user_id = u.id
    WHERE rm.room_id = ?
  `, [roomId]);

  const lastMessage = queryOne(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip
    FROM messages m
    JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ?
    ORDER BY m.created_at DESC
    LIMIT 1
  `, [roomId]);

  const unreadRow = queryOne(`
    SELECT COUNT(*) as count FROM messages m
    WHERE m.room_id = ? AND m.sender_id != ?
    AND m.id NOT IN (
      SELECT rr.message_id FROM read_receipts rr WHERE rr.user_id = ?
    )
  `, [roomId, userId, userId]);

  return {
    id: room.id,
    name: room.name,
    isGroup: !!room.is_group,
    createdBy: room.created_by,
    createdAt: room.created_at,
    members: members.map((m: any) => ({
      id: m.id,
      ip: m.ip,
      name: m.name,
      isBot: !!m.is_bot,
      createdAt: m.created_at,
      updatedAt: m.updated_at,
    })),
    lastMessage: lastMessage
      ? {
          id: lastMessage.id,
          roomId: lastMessage.room_id,
          senderId: lastMessage.sender_id,
          content: lastMessage.is_deleted ? '' : lastMessage.content,
          type: lastMessage.type,
          fileUrl: lastMessage.file_url,
          fileName: lastMessage.file_name,
          fileSize: lastMessage.file_size,
          isEdited: !!lastMessage.is_edited,
          isDeleted: !!lastMessage.is_deleted,
          mentions: lastMessage.mentions,
          createdAt: lastMessage.created_at,
          updatedAt: lastMessage.updated_at,
          senderName: lastMessage.sender_name,
          senderIp: lastMessage.sender_ip,
          readBy: [] as number[],
        }
      : null,
    unreadCount: unreadRow?.count || 0,
  };
}

function fetchMessages(sql: string, params: any[]): any[] {
  const rows = queryAll(sql, params);
  return rows.map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    m._readBy = readBy.map((r: any) => r.user_id);
    return buildMessageData(m);
  });
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

// GET /rooms?userId=N
router.get('/', (req: Request, res: Response) => {
  const userId = Number(req.query.userId);
  if (!userId) {
    res.status(400).json({ error: 'userId is required.' });
    return;
  }

  const rooms = queryAll(`
    SELECT r.*, rm.joined_at
    FROM rooms r
    JOIN room_members rm ON rm.room_id = r.id
    WHERE rm.user_id = ?
    ORDER BY r.created_at DESC
  `, [userId]);

  const result = rooms.map((room: any) => buildRoomResponse(room.id, userId));

  result.sort((a: any, b: any) => {
    const aTime = a.lastMessage?.createdAt || a.createdAt;
    const bTime = b.lastMessage?.createdAt || b.createdAt;
    return bTime.localeCompare(aTime);
  });

  res.json(result);
});

// POST /rooms
router.post('/', (req: Request, res: Response) => {
  const { name, isGroup, memberIds, userId } = req.body;

  if (!userId) {
    res.status(400).json({ error: 'userId is required.' });
    return;
  }
  if (!memberIds || !Array.isArray(memberIds) || memberIds.length === 0) {
    res.status(400).json({ error: 'memberIds is required (non-empty array).' });
    return;
  }

  // For 1:1 chat, return existing room if already present
  if (!isGroup && memberIds.length === 1) {
    const existingRoom = queryOne(`
      SELECT r.id FROM rooms r
      WHERE r.is_group = 0
      AND (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) = 2
      AND EXISTS (SELECT 1 FROM room_members rm WHERE rm.room_id = r.id AND rm.user_id = ?)
      AND EXISTS (SELECT 1 FROM room_members rm WHERE rm.room_id = r.id AND rm.user_id = ?)
    `, [userId, memberIds[0]]);
    if (existingRoom) {
      res.json(buildRoomResponse(existingRoom.id, userId));
      return;
    }
  }

  const roomName = name || (isGroup ? 'Group Chat' : '');
  const result = run('INSERT INTO rooms (name, is_group, created_by) VALUES (?, ?, ?)', [
    roomName, isGroup ? 1 : 0, userId,
  ]);
  const roomId = result.lastInsertRowid;

  const allMemberIds = [userId, ...memberIds.filter((id: number) => id !== userId)];
  for (const memberId of allMemberIds) {
    run('INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)', [roomId, memberId]);
  }

  // For 1:1, set room name to the other person's name
  if (!isGroup) {
    const otherUser = queryOne('SELECT name FROM users WHERE id = ?', [memberIds[0]]);
    if (otherUser) {
      run('UPDATE rooms SET name = ? WHERE id = ?', [otherUser.name, roomId]);
    }
  }

  const room = buildRoomResponse(roomId, userId);
  if (ioInstance) {
    ioInstance.emit('room_created', room);
  }
  res.status(201).json(room);
});

// POST /rooms/:id/members
router.post('/:id/members', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const { memberIds } = req.body;

  if (!memberIds || !Array.isArray(memberIds)) {
    res.status(400).json({ error: 'memberIds is required.' });
    return;
  }
  if (!queryOne('SELECT * FROM rooms WHERE id = ?', [roomId])) {
    res.status(404).json({ error: 'Room not found.' });
    return;
  }

  for (const memberId of memberIds) {
    run('INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)', [roomId, memberId]);
  }
  res.json({ success: true });
});

// GET /rooms/:id/messages
router.get('/:id/messages', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const before = req.query.before as string | undefined;
  const limit = Math.min(Number(req.query.limit) || 50, 100);

  const params: any[] = [roomId];
  let where = '';
  if (before) {
    where = ' AND m.id < ?';
    params.push(Number(before));
  }
  params.push(limit);

  res.json(fetchMessages(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ?${where}
    ORDER BY m.created_at DESC LIMIT ?
  `, params).reverse());
});

// GET /rooms/:id/messages/around/:messageId
router.get('/:id/messages/around/:messageId', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const messageId = Number(req.params.messageId);
  const range = Math.min(Number(req.query.range) || 25, 50);

  if (!queryOne('SELECT id FROM messages WHERE id = ? AND room_id = ?', [messageId, roomId])) {
    res.status(404).json({ error: 'Message not found in this room.' });
    return;
  }

  const msgSql = `
    SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ?
  `;

  const before = queryAll(msgSql + ' AND m.id < ? ORDER BY m.id DESC LIMIT ?', [roomId, messageId, range]);
  const self   = queryAll(msgSql + ' AND m.id = ?', [roomId, messageId]);
  const after  = queryAll(msgSql + ' AND m.id > ? ORDER BY m.id ASC LIMIT ?', [roomId, messageId, range]);

  const combined = [...before.reverse(), ...self, ...after];
  res.json(combined.map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    m._readBy = readBy.map((r: any) => r.user_id);
    return buildMessageData(m);
  }));
});

// GET /rooms/:id/search?q=...
router.get('/:id/search', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const q = (req.query.q as string || '').trim();
  const limit = Math.min(Number(req.query.limit) || 30, 100);

  if (!q) {
    res.status(400).json({ error: 'Query parameter "q" is required.' });
    return;
  }

  res.json(fetchMessages(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ? AND m.is_deleted = 0 AND m.content LIKE ?
    ORDER BY m.created_at DESC LIMIT ?
  `, [roomId, `%${q}%`, limit]));
});

// GET /rooms/:id/pins
router.get('/:id/pins', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const pins = queryAll(`
    SELECT pm.id as pin_id, pm.pinned_by, pm.pinned_at, pu.name as pinner_name,
           m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
    FROM pinned_messages pm
    JOIN messages m ON m.id = pm.message_id
    JOIN users u ON u.id = m.sender_id
    JOIN users pu ON pu.id = pm.pinned_by
    WHERE pm.room_id = ?
    ORDER BY pm.pinned_at DESC
  `, [roomId]);

  res.json(pins.map((p: any) => ({
    id: p.pin_id,
    messageId: p.id,
    roomId,
    pinnedBy: p.pinned_by,
    pinnedByName: p.pinner_name,
    pinnedAt: p.pinned_at,
    message: buildMessageData(p),
  })));
});

export { buildRoomResponse };
export default router;
