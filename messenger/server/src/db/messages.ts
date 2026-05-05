/**
 * Shared message-building helpers used across api.ts, rooms.ts, and socket/handler.ts.
 * Single source of truth for how a message row is shaped into an API response object.
 */
import { queryAll, queryOne } from './index.js';
import type { MessageAttachment } from '../../../shared/types.js';

function nameFromUrl(fileUrl: string): string {
  return fileUrl.split('/').filter(Boolean).pop() || 'attachment';
}

function coerceAttachment(raw: any): MessageAttachment | null {
  if (!raw || typeof raw !== 'object') return null;
  const fileUrl = typeof raw.fileUrl === 'string' ? raw.fileUrl.trim() : '';
  if (!fileUrl) return null;

  const fileName = typeof raw.fileName === 'string' && raw.fileName.trim()
    ? raw.fileName.trim()
    : nameFromUrl(fileUrl);
  const fileSize = Number.isFinite(Number(raw.fileSize)) ? Number(raw.fileSize) : 0;
  const type = raw.type === 'image' ? 'image' : 'file';

  return {
    fileUrl,
    fileName,
    fileSize,
    mimeType: typeof raw.mimeType === 'string' ? raw.mimeType : null,
    type,
  };
}

export function parseMessageAttachments(row: any): MessageAttachment[] {
  if (!row || row.is_deleted) return [];

  if (typeof row.attachments === 'string' && row.attachments.trim()) {
    try {
      const parsed = JSON.parse(row.attachments);
      if (Array.isArray(parsed)) {
        const attachments = parsed
          .map(coerceAttachment)
          .filter((item): item is MessageAttachment => item !== null);
        if (attachments.length > 0) return attachments;
      }
    } catch {
      // Fall back to legacy single-file columns below.
    }
  }

  if (typeof row.file_url === 'string' && row.file_url.trim()) {
    return [{
      fileUrl: row.file_url,
      fileName: row.file_name || nameFromUrl(row.file_url),
      fileSize: Number.isFinite(Number(row.file_size)) ? Number(row.file_size) : 0,
      mimeType: null,
      type: row.type === 'image' ? 'image' : 'file',
    }];
  }

  return [];
}

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
    attachments: parseMessageAttachments(row),
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
    attachments: parseMessageAttachments(m),
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
