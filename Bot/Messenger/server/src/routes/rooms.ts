import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../db/index.js';

const router = Router();

let ioInstance: any = null;

export function setRoomsIo(io: any) {
  ioInstance = io;
}

function getReactionsForMessage(messageId: number) {
  const rows = queryAll(
    `SELECT mr.emoji, mr.user_id, u.name as user_name
     FROM message_reactions mr JOIN users u ON u.id = mr.user_id
     WHERE mr.message_id = ? ORDER BY mr.created_at`,
    [messageId],
  );
  const map = new Map<string, { userIds: number[]; userNames: string[] }>();
  for (const r of rows) {
    if (!map.has(r.emoji)) map.set(r.emoji, { userIds: [], userNames: [] });
    const entry = map.get(r.emoji)!;
    entry.userIds.push(r.user_id);
    entry.userNames.push(r.user_name);
  }
  return Array.from(map.entries()).map(([emoji, data]) => ({ emoji, ...data }));
}

function getReplyTo(replyToId: number | null): any {
  if (!replyToId) return null;
  const row = queryOne(
    `SELECT m.*, u.name as sender_name, u.ip as sender_ip
     FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id = ?`,
    [replyToId],
  );
  if (!row) return null;
  return {
    id: row.id, roomId: row.room_id, senderId: row.sender_id,
    content: row.is_deleted ? '' : row.content, type: row.type,
    fileUrl: row.is_deleted ? null : row.file_url,
    fileName: row.is_deleted ? null : row.file_name,
    fileSize: row.is_deleted ? null : row.file_size,
    isEdited: !!row.is_edited, isDeleted: !!row.is_deleted,
    mentions: row.mentions, replyToId: null,
    createdAt: row.created_at, updatedAt: row.updated_at,
    senderName: row.sender_name, senderIp: row.sender_ip,
    readBy: [], reactions: [], replyTo: null,
  };
}

// GET /rooms?userId=N - 사용자의 채팅방 목록
router.get('/', (req: Request, res: Response) => {
  const userId = Number(req.query.userId);
  if (!userId) {
    res.status(400).json({ error: 'userId가 필요합니다.' });
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

  // Sort by last message time
  result.sort((a: any, b: any) => {
    const aTime = a.lastMessage?.createdAt || a.createdAt;
    const bTime = b.lastMessage?.createdAt || b.createdAt;
    return bTime.localeCompare(aTime);
  });

  res.json(result);
});

// POST /rooms - 채팅방 생성
router.post('/', (req: Request, res: Response) => {
  const { name, isGroup, memberIds, userId } = req.body;

  if (!userId) {
    res.status(400).json({ error: 'userId가 필요합니다.' });
    return;
  }

  if (!memberIds || !Array.isArray(memberIds) || memberIds.length === 0) {
    res.status(400).json({ error: '멤버를 선택해주세요.' });
    return;
  }

  // For 1:1 chat, check if room already exists
  if (!isGroup && memberIds.length === 1) {
    const existingRoom = queryOne(`
      SELECT r.id FROM rooms r
      WHERE r.is_group = 0
      AND (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) = 2
      AND EXISTS (SELECT 1 FROM room_members rm WHERE rm.room_id = r.id AND rm.user_id = ?)
      AND EXISTS (SELECT 1 FROM room_members rm WHERE rm.room_id = r.id AND rm.user_id = ?)
    `, [userId, memberIds[0]]);

    if (existingRoom) {
      const room = buildRoomResponse(existingRoom.id, userId);
      res.json(room);
      return;
    }
  }

  const roomName = name || (isGroup ? '그룹 채팅' : '');
  const result = run('INSERT INTO rooms (name, is_group, created_by) VALUES (?, ?, ?)', [
    roomName,
    isGroup ? 1 : 0,
    userId,
  ]);

  const roomId = result.lastInsertRowid;

  // Add creator and members
  const allMemberIds = [userId, ...memberIds.filter((id: number) => id !== userId)];
  for (const memberId of allMemberIds) {
    run('INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)', [roomId, memberId]);
  }

  // If 1:1 room, set name to the other person's name for display
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

// POST /rooms/:id/members - 멤버 추가
router.post('/:id/members', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const { memberIds } = req.body;

  if (!memberIds || !Array.isArray(memberIds)) {
    res.status(400).json({ error: 'memberIds가 필요합니다.' });
    return;
  }

  const room = queryOne('SELECT * FROM rooms WHERE id = ?', [roomId]);
  if (!room) {
    res.status(404).json({ error: '채팅방을 찾을 수 없습니다.' });
    return;
  }

  for (const memberId of memberIds) {
    run('INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?)', [roomId, memberId]);
  }

  res.json({ success: true });
});

// GET /rooms/:id/messages - 메시지 목록
router.get('/:id/messages', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const before = req.query.before as string | undefined;
  const limit = Math.min(Number(req.query.limit) || 50, 100);

  let sql = `
    SELECT m.*, u.name as sender_name, u.ip as sender_ip
    FROM messages m
    JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ?
  `;
  const params: any[] = [roomId];

  if (before) {
    sql += ' AND m.id < ?';
    params.push(Number(before));
  }

  sql += ' ORDER BY m.created_at DESC LIMIT ?';
  params.push(limit);

  const messages = queryAll(sql, params);

  const result = messages.reverse().map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    return {
      id: m.id,
      roomId: m.room_id,
      senderId: m.sender_id,
      content: m.is_deleted ? '' : m.content,
      type: m.type,
      fileUrl: m.is_deleted ? null : m.file_url,
      fileName: m.is_deleted ? null : m.file_name,
      fileSize: m.is_deleted ? null : m.file_size,
      isEdited: !!m.is_edited,
      isDeleted: !!m.is_deleted,
      mentions: m.mentions,
      replyToId: m.reply_to || null,
      createdAt: m.created_at,
      updatedAt: m.updated_at,
      senderName: m.sender_name,
      senderIp: m.sender_ip,
      readBy: readBy.map((r: any) => r.user_id),
      reactions: getReactionsForMessage(m.id),
      replyTo: getReplyTo(m.reply_to),
    };
  });

  res.json(result);
});

// GET /rooms/:id/messages/around/:messageId - fetch messages centered on a specific message
router.get('/:id/messages/around/:messageId', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const messageId = Number(req.params.messageId);
  const range = Math.min(Number(req.query.range) || 25, 50);

  const target = queryOne('SELECT id FROM messages WHERE id = ? AND room_id = ?', [messageId, roomId]);
  if (!target) {
    res.status(404).json({ error: 'Message not found in this room.' });
    return;
  }

  const before = queryAll(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ? AND m.id < ?
    ORDER BY m.id DESC LIMIT ?
  `, [roomId, messageId, range]);

  const self = queryAll(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ? AND m.id = ?
  `, [roomId, messageId]);

  const after = queryAll(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ? AND m.id > ?
    ORDER BY m.id ASC LIMIT ?
  `, [roomId, messageId, range]);

  const combined = [...before.reverse(), ...self, ...after];

  const result = combined.map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    return {
      id: m.id, roomId: m.room_id, senderId: m.sender_id,
      content: m.is_deleted ? '' : m.content, type: m.type,
      fileUrl: m.is_deleted ? null : m.file_url,
      fileName: m.is_deleted ? null : m.file_name,
      fileSize: m.is_deleted ? null : m.file_size,
      isEdited: !!m.is_edited, isDeleted: !!m.is_deleted,
      mentions: m.mentions, replyToId: m.reply_to || null,
      createdAt: m.created_at, updatedAt: m.updated_at,
      senderName: m.sender_name, senderIp: m.sender_ip,
      readBy: readBy.map((r: any) => r.user_id),
      reactions: getReactionsForMessage(m.id),
      replyTo: getReplyTo(m.reply_to),
    };
  });

  res.json(result);
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

  const rows = queryAll(`
    SELECT m.*, u.name as sender_name, u.ip as sender_ip
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ? AND m.is_deleted = 0 AND m.content LIKE ?
    ORDER BY m.created_at DESC LIMIT ?
  `, [roomId, `%${q}%`, limit]);

  const results = rows.map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    return {
      id: m.id, roomId: m.room_id, senderId: m.sender_id,
      content: m.is_deleted ? '' : m.content, type: m.type,
      fileUrl: m.is_deleted ? null : m.file_url,
      fileName: m.is_deleted ? null : m.file_name,
      fileSize: m.is_deleted ? null : m.file_size,
      isEdited: !!m.is_edited, isDeleted: !!m.is_deleted,
      mentions: m.mentions, replyToId: m.reply_to || null,
      createdAt: m.created_at, updatedAt: m.updated_at,
      senderName: m.sender_name, senderIp: m.sender_ip,
      readBy: readBy.map((r: any) => r.user_id),
      reactions: getReactionsForMessage(m.id),
      replyTo: getReplyTo(m.reply_to),
    };
  });

  res.json(results);
});

// POST /rooms/:id/leave
router.post('/:id/leave', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const { userId } = req.body;
  if (!userId) {
    res.status(400).json({ error: 'userId is required.' });
    return;
  }

  run('DELETE FROM read_receipts WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)', [roomId]);
  run('DELETE FROM message_reactions WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)', [roomId]);
  run('DELETE FROM pinned_messages WHERE room_id = ?', [roomId]);
  run('DELETE FROM messages WHERE room_id = ?', [roomId]);
  run('DELETE FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, userId]);

  if (ioInstance) {
    const user = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
    const userName = user?.name || 'Unknown';
    ioInstance.to(`room:${roomId}`).emit('room_messages_cleared', { roomId, userId, userName });
    ioInstance.to(`room:${roomId}`).emit('member_left', { roomId, userId, userName });
  }

  res.json({ success: true });
});

// GET /rooms/:id/pins
router.get('/:id/pins', (req: Request, res: Response) => {
  const roomId = Number(req.params.id);
  const pins = queryAll(`
    SELECT pm.id as pin_id, pm.pinned_by, pm.pinned_at, pu.name as pinner_name,
           m.*, u.name as sender_name, u.ip as sender_ip
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
    message: {
      id: p.id, roomId: p.room_id, senderId: p.sender_id,
      content: p.is_deleted ? '' : p.content, type: p.type,
      fileUrl: p.is_deleted ? null : p.file_url,
      fileName: p.is_deleted ? null : p.file_name,
      fileSize: p.is_deleted ? null : p.file_size,
      isEdited: !!p.is_edited, isDeleted: !!p.is_deleted,
      mentions: p.mentions, replyToId: p.reply_to || null,
      createdAt: p.created_at, updatedAt: p.updated_at,
      senderName: p.sender_name, senderIp: p.sender_ip,
      readBy: [], reactions: getReactionsForMessage(p.id), replyTo: getReplyTo(p.reply_to),
    },
  })));
});

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

export { buildRoomResponse };
export default router;
