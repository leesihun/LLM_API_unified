/**
 * Shared message-building helpers used across api.ts, rooms.ts, and socket/handler.ts.
 * Single source of truth for how a message row is shaped into an API response object.
 */
import { queryAll, queryOne } from './index.js';

export function getReactionsForMessage(messageId: number) {
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

export function getReplyTo(replyToId: number | null): any {
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

/**
 * Build a full message API response object from a DB row.
 * Pre-attach `m._readBy` (number[]) before calling if you have read receipts available;
 * otherwise readBy defaults to [].
 * The row must include sender_name, sender_ip, and sender_is_bot columns.
 */
export function buildMessageData(m: any) {
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
