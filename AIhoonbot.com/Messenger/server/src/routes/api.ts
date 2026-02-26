import { Router, Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import crypto from 'crypto';
import { v4 as uuidv4 } from 'uuid';
import { queryAll, queryOne, run } from '../db/index.js';
import { apiKeyAuth } from '../middleware/apiAuth.js';
import { dispatchWebhooks } from '../services/webhook.js';
import { startWatcher, stopWatcher } from '../services/web-poller.js';

const router = Router();
router.use(apiKeyAuth);

let ioInstance: any = null;

export function setIoInstance(io: any) {
  ioInstance = io;
}

// ===========================================================================
// FILE UPLOAD SETUP
// ===========================================================================

const UPLOADS_DIR = path.join(__dirname, '..', '..', 'uploads');
if (!fs.existsSync(UPLOADS_DIR)) {
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });
}

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    const dateFolder = new Date().toISOString().slice(0, 10);
    const dir = path.join(UPLOADS_DIR, dateFolder);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    cb(null, dir);
  },
  filename: (_req, _file, cb) => {
    const ext = path.extname(_file.originalname);
    cb(null, `${uuidv4()}${ext}`);
  },
});

const upload = multer({ storage, limits: { fileSize: 100 * 1024 * 1024 } });

// ===========================================================================
// HELPERS
// ===========================================================================

/**
 * Resolve the sender from (in priority order):
 *   1. x-api-key header (attached by apiKeyAuth middleware)
 *   2. senderId in body or query (strict ID-based identity)
 *   3. senderName in body or query (globally unique)
 */
function resolveSender(req: Request): any | null {
  if ((req as any).apiUser) return (req as any).apiUser;
  const { body, query } = req;
  const senderIdRaw = body.senderId ?? query.senderId;
  const senderName = body.senderName || query.senderName;
  if (senderIdRaw !== undefined && senderIdRaw !== null && String(senderIdRaw).trim() !== '') {
    const senderId = Number(senderIdRaw);
    if (Number.isInteger(senderId) && senderId > 0) {
      return queryOne('SELECT * FROM users WHERE id = ?', [senderId]);
    }
    return null;
  }
  if (senderName) return queryOne('SELECT * FROM users WHERE name = ?', [senderName]);
  return null;
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
    `SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
     FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id = ?`,
    [replyToId],
  );
  if (!row) return null;
  return {
    id: row.id,
    roomId: row.room_id,
    senderId: row.sender_id,
    content: row.is_deleted ? '' : row.content,
    type: row.type,
    fileUrl: row.is_deleted ? null : row.file_url,
    fileName: row.is_deleted ? null : row.file_name,
    fileSize: row.is_deleted ? null : row.file_size,
    isEdited: !!row.is_edited,
    isDeleted: !!row.is_deleted,
    mentions: row.mentions,
    replyToId: null,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    senderName: row.sender_name,
    senderIp: row.sender_ip,
    isBot: !!row.sender_is_bot,
    readBy: [],
    reactions: [],
    replyTo: null,
  };
}

function buildMessageData(m: any) {
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
    isBot: !!m.sender_is_bot,
    readBy: (m._readBy ?? []) as number[],
    reactions: getReactionsForMessage(m.id),
    replyTo: getReplyTo(m.reply_to),
  };
}

function generateApiKey(): string {
  return 'huni_' + crypto.randomBytes(24).toString('hex');
}

function fetchFullMessage(messageId: number) {
  return queryOne(
    `SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
     FROM messages m JOIN users u ON u.id = m.sender_id
     WHERE m.id = ?`,
    [messageId],
  );
}

// ===========================================================================
// MESSAGES
// ===========================================================================

// POST /api/send-message
router.post('/send-message', (req: Request, res: Response) => {
  const {
    roomId, content, type = 'text',
    fileUrl = null, fileName = null, fileSize = null,
    mentions = [], replyToId = null,
  } = req.body;

  if (!roomId || !content) {
    res.status(400).json({ error: 'roomId and content are required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found. Provide senderId, senderName, or x-api-key header.' });
    return;
  }

  const membership = queryOne(
    'SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?',
    [roomId, sender.id],
  );
  if (!membership) {
    res.status(403).json({ error: 'Sender is not a member of this room.' });
    return;
  }

  const mentionsJson = JSON.stringify(mentions);
  const result = run(
    'INSERT INTO messages (room_id, sender_id, content, type, file_url, file_name, file_size, mentions, reply_to) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
    [roomId, sender.id, content, type, fileUrl, fileName, fileSize, mentionsJson, replyToId],
  );

  const msg = fetchFullMessage(result.lastInsertRowid);
  const messageData = buildMessageData(msg);

  if (ioInstance) {
    ioInstance.to(`room:${roomId}`).emit('new_message', messageData);
  }
  dispatchWebhooks('new_message', roomId, messageData);

  res.status(201).json({ success: true, message: messageData });
});

// POST /api/send-file  (multipart upload + send in one step)
router.post('/send-file', upload.single('file'), (req: Request, res: Response) => {
  if (!req.file) {
    res.status(400).json({ error: 'No file attached.' });
    return;
  }

  const { roomId, content } = req.body;
  if (!roomId) {
    res.status(400).json({ error: 'roomId is required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const membership = queryOne(
    'SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?',
    [roomId, sender.id],
  );
  if (!membership) {
    res.status(403).json({ error: 'Sender is not a member of this room.' });
    return;
  }

  const dateFolder = new Date().toISOString().slice(0, 10);
  const fileUrl = `/uploads/${dateFolder}/${req.file.filename}`;
  const fName = req.file.originalname;
  const fSize = req.file.size;
  const isImage = /\.(jpg|jpeg|png|gif|webp|bmp|svg)$/i.test(fName);
  const msgType = isImage ? 'image' : 'file';
  const msgContent = content || fName;

  const result = run(
    "INSERT INTO messages (room_id, sender_id, content, type, file_url, file_name, file_size, mentions) VALUES (?, ?, ?, ?, ?, ?, ?, '[]')",
    [roomId, sender.id, msgContent, msgType, fileUrl, fName, fSize],
  );

  const msg = fetchFullMessage(result.lastInsertRowid);
  const messageData = buildMessageData(msg);

  if (ioInstance) {
    ioInstance.to(`room:${Number(roomId)}`).emit('new_message', messageData);
  }
  dispatchWebhooks('new_message', Number(roomId), messageData);

  res.status(201).json({ success: true, message: messageData });
});

// POST /api/send-base64  (base64 image upload + send)
router.post('/send-base64', (req: Request, res: Response) => {
  const { data, roomId, content, fileName } = req.body;

  if (!data || !roomId) {
    res.status(400).json({ error: 'data and roomId are required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const membership = queryOne(
    'SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?',
    [roomId, sender.id],
  );
  if (!membership) {
    res.status(403).json({ error: 'Sender is not a member of this room.' });
    return;
  }

  const base64Data = data.replace(/^data:image\/\w+;base64,/, '');
  const buffer = Buffer.from(base64Data, 'base64');

  let ext = '.png';
  const mimeMatch = data.match(/^data:image\/(\w+);base64,/);
  if (mimeMatch) {
    ext = '.' + mimeMatch[1].replace('jpeg', 'jpg');
  }

  const dateFolder = new Date().toISOString().slice(0, 10);
  const dir = path.join(UPLOADS_DIR, dateFolder);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const uniqueName = `${uuidv4()}${ext}`;
  fs.writeFileSync(path.join(dir, uniqueName), buffer);

  const fileUrl = `/uploads/${dateFolder}/${uniqueName}`;
  const fName = fileName || `image${ext}`;
  const fSize = buffer.length;
  const msgContent = content || fName;

  const result = run(
    "INSERT INTO messages (room_id, sender_id, content, type, file_url, file_name, file_size, mentions) VALUES (?, ?, ?, 'image', ?, ?, ?, '[]')",
    [roomId, sender.id, msgContent, fileUrl, fName, fSize],
  );

  const msg = fetchFullMessage(result.lastInsertRowid);
  const messageData = buildMessageData(msg);

  if (ioInstance) {
    ioInstance.to(`room:${Number(roomId)}`).emit('new_message', messageData);
  }
  dispatchWebhooks('new_message', Number(roomId), messageData);

  res.status(201).json({ success: true, message: messageData });
});

// POST /api/upload-file  (upload only, returns URL)
router.post('/upload-file', upload.single('file'), (req: Request, res: Response) => {
  if (!req.file) {
    res.status(400).json({ error: 'No file attached.' });
    return;
  }
  const dateFolder = new Date().toISOString().slice(0, 10);
  res.json({
    fileUrl: `/uploads/${dateFolder}/${req.file.filename}`,
    fileName: req.file.originalname,
    fileSize: req.file.size,
  });
});

// GET /api/messages/:roomId  (paginated, supports ?before, ?after, ?limit)
router.get('/messages/:roomId', (req: Request, res: Response) => {
  const roomId = Number(req.params.roomId);
  const limit = Math.min(Number(req.query.limit) || 50, 100);
  const before = req.query.before ? Number(req.query.before) : null;
  const after = req.query.after ? Number(req.query.after) : null;

  const room = queryOne('SELECT 1 FROM rooms WHERE id = ?', [roomId]);
  if (!room) {
    res.status(404).json({ error: 'Room not found.' });
    return;
  }

  let sql = `
    SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.room_id = ?
  `;
  const params: any[] = [roomId];

  if (before) { sql += ' AND m.id < ?'; params.push(before); }
  if (after)  { sql += ' AND m.id > ?'; params.push(after); }

  sql += ' ORDER BY m.id DESC LIMIT ?';
  params.push(limit);

  const rows = queryAll(sql, params);
  const messages = rows.reverse().map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    m._readBy = readBy.map((r: any) => r.user_id);
    return buildMessageData(m);
  });

  res.json(messages);
});

// POST /api/edit-message
router.post('/edit-message', (req: Request, res: Response) => {
  const { messageId, content } = req.body;
  if (!messageId || content === undefined) {
    res.status(400).json({ error: 'messageId and content are required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const message = queryOne('SELECT sender_id, room_id FROM messages WHERE id = ?', [messageId]);
  if (!message) {
    res.status(404).json({ error: 'Message not found.' });
    return;
  }
  if (message.sender_id !== sender.id) {
    res.status(403).json({ error: 'You can only edit your own messages.' });
    return;
  }

  run("UPDATE messages SET content = ?, is_edited = 1, updated_at = datetime('now') WHERE id = ?", [content, messageId]);
  const updated = queryOne('SELECT updated_at FROM messages WHERE id = ?', [messageId]);
  const payload = { messageId, content, updatedAt: updated.updated_at };

  if (ioInstance) {
    ioInstance.to(`room:${message.room_id}`).emit('message_edited', payload);
  }
  dispatchWebhooks('message_edited', message.room_id, payload);

  res.json({ success: true, ...payload });
});

// POST /api/delete-message
router.post('/delete-message', (req: Request, res: Response) => {
  const { messageId } = req.body;
  if (!messageId) {
    res.status(400).json({ error: 'messageId is required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  const message = queryOne('SELECT sender_id, room_id FROM messages WHERE id = ?', [messageId]);
  if (!message) {
    res.status(404).json({ error: 'Message not found.' });
    return;
  }
  if (message.sender_id !== sender.id) {
    res.status(403).json({ error: 'You can only delete your own messages.' });
    return;
  }

  run("UPDATE messages SET is_deleted = 1, content = '', updated_at = datetime('now') WHERE id = ?", [messageId]);
  const payload = { messageId };

  if (ioInstance) {
    ioInstance.to(`room:${message.room_id}`).emit('message_deleted', payload);
  }
  dispatchWebhooks('message_deleted', message.room_id, payload);

  res.json({ success: true });
});

// POST /api/mark-read
router.post('/mark-read', (req: Request, res: Response) => {
  const { roomId, messageIds } = req.body;
  if (!roomId || !Array.isArray(messageIds) || messageIds.length === 0) {
    res.status(400).json({ error: 'roomId and messageIds[] are required.' });
    return;
  }

  const sender = resolveSender(req);
  if (!sender) {
    res.status(404).json({ error: 'Sender not found.' });
    return;
  }

  for (const msgId of messageIds) {
    run('INSERT OR IGNORE INTO read_receipts (message_id, user_id) VALUES (?, ?)', [msgId, sender.id]);
    if (ioInstance) {
      ioInstance.to(`room:${roomId}`).emit('message_read', { messageId: msgId, userId: sender.id, roomId });
    }
  }

  res.json({ success: true, markedCount: messageIds.length });
});

// ===========================================================================
// SEARCH
// ===========================================================================

// GET /api/search?q=...&roomId=...&limit=...
router.get('/search', (req: Request, res: Response) => {
  const q = (req.query.q as string || '').trim();
  if (!q) {
    res.status(400).json({ error: 'Query parameter "q" is required.' });
    return;
  }

  const roomId = req.query.roomId ? Number(req.query.roomId) : null;
  const limit = Math.min(Number(req.query.limit) || 50, 100);

  let sql = `
    SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
    FROM messages m JOIN users u ON u.id = m.sender_id
    WHERE m.is_deleted = 0 AND m.content LIKE ?
  `;
  const params: any[] = [`%${q}%`];

  if (roomId) {
    sql += ' AND m.room_id = ?';
    params.push(roomId);
  }

  sql += ' ORDER BY m.created_at DESC LIMIT ?';
  params.push(limit);

  const rows = queryAll(sql, params);
  const messages = rows.map((m: any) => {
    const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [m.id]);
    m._readBy = readBy.map((r: any) => r.user_id);
    return buildMessageData(m);
  });

  res.json(messages);
});

// ===========================================================================
// REACTIONS
// ===========================================================================

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

  const message = queryOne('SELECT room_id FROM messages WHERE id = ?', [messageId]);
  if (!message) {
    res.status(404).json({ error: 'Message not found.' });
    return;
  }

  const existing = queryOne(
    'SELECT id FROM message_reactions WHERE message_id = ? AND user_id = ? AND emoji = ?',
    [messageId, sender.id, emoji],
  );
  if (existing) {
    run('DELETE FROM message_reactions WHERE id = ?', [existing.id]);
  } else {
    run('INSERT INTO message_reactions (message_id, user_id, emoji) VALUES (?, ?, ?)', [messageId, sender.id, emoji]);
  }

  // Build current reaction state
  const rows = queryAll(
    `SELECT mr.emoji, mr.user_id, u.name as user_name
     FROM message_reactions mr JOIN users u ON u.id = mr.user_id
     WHERE mr.message_id = ? ORDER BY mr.created_at`,
    [messageId],
  );
  const reactionMap = new Map<string, { userIds: number[]; userNames: string[] }>();
  for (const r of rows) {
    if (!reactionMap.has(r.emoji)) reactionMap.set(r.emoji, { userIds: [], userNames: [] });
    const entry = reactionMap.get(r.emoji)!;
    entry.userIds.push(r.user_id);
    entry.userNames.push(r.user_name);
  }
  const reactions = Array.from(reactionMap.entries()).map(([e, data]) => ({ emoji: e, ...data }));

  if (ioInstance) {
    ioInstance.to(`room:${message.room_id}`).emit('reaction_updated', { messageId, roomId: message.room_id, reactions });
  }

  res.json({ success: true, reactions });
});

// ===========================================================================
// PINNED MESSAGES
// ===========================================================================

// GET /api/pins/:roomId
router.get('/pins/:roomId', (req: Request, res: Response) => {
  const roomId = Number(req.params.roomId);
  const pins = queryAll(
    `SELECT pm.*, m.*, u.name as sender_name, u.ip as sender_ip, pu.name as pinner_name
     FROM pinned_messages pm
     JOIN messages m ON m.id = pm.message_id
     JOIN users u ON u.id = m.sender_id
     JOIN users pu ON pu.id = pm.pinned_by
     WHERE pm.room_id = ?
     ORDER BY pm.pinned_at DESC`,
    [roomId],
  );

  const result = pins.map((p: any) => ({
    id: p.id,
    messageId: p.message_id,
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

// ===========================================================================
// LEAVE ROOM
// ===========================================================================

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

  const membership = queryOne(
    'SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?',
    [roomId, sender.id],
  );
  if (!membership) {
    res.status(404).json({ error: 'Not a member of this room.' });
    return;
  }

  run('DELETE FROM read_receipts WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)', [roomId]);
  run('DELETE FROM message_reactions WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)', [roomId]);
  run('DELETE FROM pinned_messages WHERE room_id = ?', [roomId]);
  run('DELETE FROM messages WHERE room_id = ?', [roomId]);
  run('DELETE FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, sender.id]);

  if (ioInstance) {
    ioInstance.to(`room:${roomId}`).emit('room_messages_cleared', { roomId, userId: sender.id, userName: sender.name });
    ioInstance.to(`room:${roomId}`).emit('member_left', { roomId, userId: sender.id, userName: sender.name });
  }

  res.json({ success: true });
});

// ===========================================================================
// ROOMS
// ===========================================================================

// GET /api/rooms
router.get('/rooms', (req: Request, res: Response) => {
  const userId = Number(req.query.userId);

  let rooms;
  if (userId) {
    rooms = queryAll(`
      SELECT r.* FROM rooms r
      JOIN room_members rm ON rm.room_id = r.id
      WHERE rm.user_id = ?
      ORDER BY r.created_at DESC
    `, [userId]);
  } else {
    rooms = queryAll('SELECT * FROM rooms ORDER BY created_at DESC');
  }

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

  if (ioInstance) {
    const createdRoom = queryOne('SELECT * FROM rooms WHERE id = ?', [roomId]);
    const members = queryAll(`
      SELECT u.id, u.name, u.ip, u.is_bot, u.created_at, u.updated_at FROM users u
      JOIN room_members rm ON rm.user_id = u.id
      WHERE rm.room_id = ?
    `, [roomId]);
    ioInstance.emit('room_created', {
      id: roomId,
      name: roomName,
      isGroup: !!isGroup,
      createdBy: creator.id,
      createdAt: createdRoom?.created_at || new Date().toISOString(),
      lastMessage: null,
      unreadCount: 0,
      members: members.map((m: any) => ({
        id: m.id,
        name: m.name,
        ip: m.ip,
        isBot: !!m.is_bot,
        createdAt: m.created_at,
        updatedAt: m.updated_at,
      })),
    });
  }

  res.status(201).json({ success: true, roomId, name: roomName, members: memberIds });
});

// ===========================================================================
// USERS
// ===========================================================================

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

// ===========================================================================
// BOT MANAGEMENT
// ===========================================================================

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

// ===========================================================================
// TYPING INDICATORS
// ===========================================================================

router.post('/typing', (req: Request, res: Response) => {
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

  if (ioInstance) {
    ioInstance.to(`room:${roomId}`).emit('user_typing', {
      roomId: Number(roomId),
      userId: sender.id,
      userName: sender.name,
    });
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

  if (ioInstance) {
    ioInstance.to(`room:${roomId}`).emit('user_stop_typing', {
      roomId: Number(roomId),
      userId: sender.id,
    });
  }

  res.json({ success: true });
});

// ===========================================================================
// WEBHOOK MANAGEMENT
// ===========================================================================

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

// ===========================================================================
// WEB WATCHER MANAGEMENT
// ===========================================================================

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

  const membership = queryOne(
    'SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?',
    [roomId, sender.id],
  );
  if (!membership) {
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
