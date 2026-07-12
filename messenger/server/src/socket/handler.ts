import { Server, Socket } from 'socket.io';
import { queryAll, queryOne, run } from '../db/index.js';
import { buildMessageData } from '../db/messages.js';
import {
  createMessage, editMessage, deleteMessage, toggleReaction,
  sanitizeAttachments, attachmentMessageType,
} from '../services/messages.js';
import type { ClientToServerEvents, MessageAttachment, ServerToClientEvents } from '../../../shared/types.js';

type TypedSocket = Socket<ClientToServerEvents, ServerToClientEvents>;
type SendMessagePayload = Parameters<ClientToServerEvents['send_message']>[0];
type EditMessagePayload = Parameters<ClientToServerEvents['edit_message']>[0];
type DeleteMessagePayload = Parameters<ClientToServerEvents['delete_message']>[0];
type ReadReceiptPayload = Parameters<ClientToServerEvents['read_receipt']>[0];
type ToggleReactionPayload = Parameters<ClientToServerEvents['toggle_reaction']>[0];
type PinMessagePayload = Parameters<ClientToServerEvents['pin_message']>[0];
type UnpinMessagePayload = Parameters<ClientToServerEvents['unpin_message']>[0];

// Track online users: userId -> Set<socketId>
const onlineUsers = new Map<number, Set<string>>();
// Track socket -> userId mapping
const socketUserMap = new Map<string, number>();
// Track typing state: socketId -> Set<roomId> (for cleanup on disconnect)
const socketTypingRooms = new Map<string, Set<number>>();

// Auto-clear typing after this many ms if no stop is received
const TYPING_TIMEOUT_MS = 15_000;
// Track typing timeouts: `${userId}:${roomId}` -> timeout handle
const typingTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

let ioRef: Server<ClientToServerEvents, ServerToClientEvents> | null = null;

/** Emit an event to all active sockets for a specific user. */
export function emitToUser(userId: number, event: string, data: any) {
  if (!ioRef) return;
  const sockets = onlineUsers.get(userId);
  if (sockets) {
    for (const socketId of sockets) {
      ioRef.to(socketId).emit(event as any, data);
    }
  }
}

function validateOutgoingMessage(type: unknown, fileUrl: unknown, attachments: MessageAttachment[]): string | null {
  if (type !== 'text' && type !== 'image' && type !== 'file') {
    return 'type must be text, image, or file.';
  }
  if ((type === 'image' || type === 'file') && attachments.length === 0 && (typeof fileUrl !== 'string' || fileUrl.trim() === '')) {
    return `${type} messages require fileUrl or attachments. Upload the file first and pass the returned fileUrl.`;
  }
  return null;
}

export function setupSocketHandlers(io: Server<ClientToServerEvents, ServerToClientEvents>) {
  ioRef = io;
  io.on('connection', (socket: TypedSocket) => {
    const userId = Number(socket.handshake.query.userId);
    if (!userId || isNaN(userId)) {
      socket.disconnect();
      return;
    }

    // Track online status
    if (!onlineUsers.has(userId)) {
      onlineUsers.set(userId, new Set());
    }
    onlineUsers.get(userId)!.add(socket.id);
    socketUserMap.set(socket.id, userId);

    // Broadcast online status
    io.emit('user_online_status', { userId, online: true });

    // Send current online users to the newly connected client
    for (const [uid] of onlineUsers) {
      if (uid !== userId) {
        socket.emit('user_online_status', { userId: uid, online: true });
      }
    }

    // Auto-join all rooms this user belongs to
    const userRooms = queryAll('SELECT room_id FROM room_members WHERE user_id = ?', [userId]);
    for (const room of userRooms) {
      socket.join(`room:${room.room_id}`);
    }

    // Join room (membership required)
    socket.on('join_room', (roomId: number) => {
      const membership = queryOne('SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, userId]);
      if (membership) socket.join(`room:${roomId}`);
    });

    // Leave room
    socket.on('leave_room', (roomId: number) => {
      socket.leave(`room:${roomId}`);
    });

    // Send message (membership required)
    socket.on('send_message', (data: SendMessagePayload) => {
      const { roomId, content, type, fileUrl, fileName, fileSize, mentions, replyToId } = data;
      const attachments = sanitizeAttachments(data.attachments);
      if (attachments.length === 0 && fileUrl) {
        attachments.push({
          fileUrl,
          fileName: fileName || fileUrl.split('/').filter(Boolean).pop() || 'attachment',
          fileSize: Number.isFinite(Number(fileSize)) ? Number(fileSize) : 0,
          mimeType: null,
          type: type === 'image' ? 'image' : 'file',
        });
      }
      const messageType = attachments.length > 0 ? attachmentMessageType(attachments) : type;

      const validationError = validateOutgoingMessage(messageType, fileUrl, attachments);
      if (validationError) {
        console.warn(`[Socket] Rejected send_message from user ${userId}: ${validationError}`);
        (socket as any).emit('message_error', { error: validationError });
        return;
      }

      const membership = queryOne('SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, userId]);
      if (!membership) return;

      const messageData = createMessage({
        roomId,
        senderId: userId,
        content,
        type: messageType,
        attachments,
        mentions: mentions || [],
        replyToId: replyToId || null,
      });
      if (!messageData) return;

      // Send mention notifications
      if (mentions && mentions.length > 0) {
        const room = queryOne('SELECT name FROM rooms WHERE id = ?', [roomId]);
        for (const mentionedUserId of mentions) {
          const mentionedSockets = onlineUsers.get(mentionedUserId);
          if (mentionedSockets) {
            for (const socketId of mentionedSockets) {
              io.to(socketId).emit('mention_notification', {
                message: messageData,
                roomName: room?.name || '',
              });
            }
          }
        }
      }
    });

    // Edit message (service enforces sender ownership)
    socket.on('edit_message', (data: EditMessagePayload) => {
      editMessage(data.messageId, userId, data.content);
    });

    // Delete message (service enforces sender ownership)
    socket.on('delete_message', (data: DeleteMessagePayload) => {
      deleteMessage(data.messageId, userId);
    });

    // Read receipt
    socket.on('read_receipt', (data: ReadReceiptPayload) => {
      const { messageId, roomId } = data;

      run('INSERT OR IGNORE INTO read_receipts (message_id, user_id) VALUES (?, ?)', [messageId, userId]);

      io.to(`room:${roomId}`).emit('message_read', { messageId, userId, roomId });
    });

    // Typing indicators — with server-side timeout to prevent stuck indicators
    socket.on('typing_start', (roomId: number) => {
      const user = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
      socket.to(`room:${roomId}`).emit('user_typing', {
        roomId,
        userId,
        userName: user?.name || 'Unknown',
      });

      // Track this socket as typing in this room (for disconnect cleanup)
      if (!socketTypingRooms.has(socket.id)) {
        socketTypingRooms.set(socket.id, new Set());
      }
      socketTypingRooms.get(socket.id)!.add(roomId);

      // Auto-clear typing after timeout
      const timeoutKey = `${userId}:${roomId}`;
      const existing = typingTimeouts.get(timeoutKey);
      if (existing) clearTimeout(existing);
      typingTimeouts.set(timeoutKey, setTimeout(() => {
        typingTimeouts.delete(timeoutKey);
        socketTypingRooms.get(socket.id)?.delete(roomId);
        io.to(`room:${roomId}`).emit('user_stop_typing', { roomId, userId });
      }, TYPING_TIMEOUT_MS));
    });

    socket.on('typing_stop', (roomId: number) => {
      socket.to(`room:${roomId}`).emit('user_stop_typing', { roomId, userId });

      // Clean up tracking
      socketTypingRooms.get(socket.id)?.delete(roomId);
      const timeoutKey = `${userId}:${roomId}`;
      const existing = typingTimeouts.get(timeoutKey);
      if (existing) {
        clearTimeout(existing);
        typingTimeouts.delete(timeoutKey);
      }
    });

    // Toggle reaction (add if not exists, remove if exists)
    socket.on('toggle_reaction', (data: ToggleReactionPayload) => {
      toggleReaction(data.messageId, userId, data.emoji);
    });

    // Pin message
    socket.on('pin_message', (data: PinMessagePayload) => {
      const { messageId, roomId } = data;
      const msg = queryOne('SELECT room_id FROM messages WHERE id = ?', [messageId]);
      if (!msg || msg.room_id !== roomId) return;

      const existing = queryOne('SELECT id FROM pinned_messages WHERE message_id = ?', [messageId]);
      if (existing) return;

      const pinResult = run('INSERT INTO pinned_messages (message_id, room_id, pinned_by) VALUES (?, ?, ?)', [messageId, roomId, userId]);

      const fullMsg = queryOne(
        `SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
         FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id = ?`,
        [messageId],
      );
      const pinner = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
      const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [messageId]);
      fullMsg._readBy = readBy.map((r: any) => r.user_id);

      const pin = {
        id: Number(pinResult.lastInsertRowid),
        messageId,
        roomId,
        pinnedBy: userId,
        pinnedByName: pinner?.name || 'Unknown',
        pinnedAt: new Date().toISOString(),
        message: buildMessageData(fullMsg),
      };
      io.to(`room:${roomId}`).emit('message_pinned', { roomId, pin });
    });

    // Unpin message
    socket.on('unpin_message', (data: UnpinMessagePayload) => {
      const { messageId, roomId } = data;
      run('DELETE FROM pinned_messages WHERE message_id = ? AND room_id = ?', [messageId, roomId]);
      io.to(`room:${roomId}`).emit('message_unpinned', { roomId, messageId });
    });

    // Leave room permanently — removes user from room, preserves history for others
    socket.on('leave_room_permanent', (roomId: number) => {
      const user = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
      const userName = user?.name || 'Unknown';

      // Clear typing indicator before leaving
      io.to(`room:${roomId}`).emit('user_stop_typing', { roomId, userId });
      socketTypingRooms.get(socket.id)?.delete(roomId);
      const timeoutKey = `${userId}:${roomId}`;
      const existingTimeout = typingTimeouts.get(timeoutKey);
      if (existingTimeout) {
        clearTimeout(existingTimeout);
        typingTimeouts.delete(timeoutKey);
      }

      run('DELETE FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, userId]);

      socket.leave(`room:${roomId}`);

      io.to(`room:${roomId}`).emit('member_left', { roomId, userId, userName });
    });

    // Disconnect — clean up typing indicators and online status
    socket.on('disconnect', () => {
      const uid = socketUserMap.get(socket.id);
      if (uid !== undefined) {
        // Clear typing indicators for all rooms this socket was typing in
        const typingRooms = socketTypingRooms.get(socket.id);
        if (typingRooms) {
          for (const roomId of typingRooms) {
            io.to(`room:${roomId}`).emit('user_stop_typing', { roomId, userId: uid });
            const timeoutKey = `${uid}:${roomId}`;
            const existing = typingTimeouts.get(timeoutKey);
            if (existing) {
              clearTimeout(existing);
              typingTimeouts.delete(timeoutKey);
            }
          }
          socketTypingRooms.delete(socket.id);
        }

        const sockets = onlineUsers.get(uid);
        if (sockets) {
          sockets.delete(socket.id);
          if (sockets.size === 0) {
            onlineUsers.delete(uid);
            io.emit('user_online_status', { userId: uid, online: false });
          }
        }
        socketUserMap.delete(socket.id);
      }
    });
  });
}
