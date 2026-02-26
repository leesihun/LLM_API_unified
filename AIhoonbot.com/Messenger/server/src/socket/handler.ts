import { Server, Socket } from 'socket.io';
import { queryAll, queryOne, run } from '../db/index.js';
import { dispatchWebhooks } from '../services/webhook.js';
import type { ClientToServerEvents, ServerToClientEvents, MessageReaction } from '../../../shared/types.js';

type TypedSocket = Socket<ClientToServerEvents, ServerToClientEvents>;

// Track online users: userId -> Set<socketId>
const onlineUsers = new Map<number, Set<string>>();
// Track socket -> userId mapping
const socketUserMap = new Map<string, number>();

function getReactionsForMessage(messageId: number): MessageReaction[] {
  const rows = queryAll(
    `SELECT mr.emoji, mr.user_id, u.name as user_name
     FROM message_reactions mr JOIN users u ON u.id = mr.user_id
     WHERE mr.message_id = ?
     ORDER BY mr.created_at`,
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
     FROM messages m JOIN users u ON u.id = m.sender_id
     WHERE m.id = ?`,
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

export function setupSocketHandlers(io: Server<ClientToServerEvents, ServerToClientEvents>) {
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

    // Join room
    socket.on('join_room', (roomId: number) => {
      socket.join(`room:${roomId}`);
    });

    // Leave room
    socket.on('leave_room', (roomId: number) => {
      socket.leave(`room:${roomId}`);
    });

    // Send message
    socket.on('send_message', (data) => {
      const { roomId, content, type, fileUrl, fileName, fileSize, mentions, replyToId } = data;

      const mentionsJson = JSON.stringify(mentions || []);

      const result = run(`
        INSERT INTO messages (room_id, sender_id, content, type, file_url, file_name, file_size, mentions, reply_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `, [roomId, userId, content, type, fileUrl || null, fileName || null, fileSize || null, mentionsJson, replyToId || null]);

      const messageId = result.lastInsertRowid;
      const message = queryOne(`
        SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.id = ?
      `, [messageId]);

      if (!message) {
        console.error(`Failed to retrieve inserted message with id ${messageId}`);
        return;
      }

      const messageData = {
        id: message.id,
        roomId: message.room_id,
        senderId: message.sender_id,
        content: message.content,
        type: message.type as 'text' | 'image' | 'file',
        fileUrl: message.file_url,
        fileName: message.file_name,
        fileSize: message.file_size,
        isEdited: false,
        isDeleted: false,
        mentions: message.mentions,
        replyToId: message.reply_to || null,
        createdAt: message.created_at,
        updatedAt: message.updated_at,
        senderName: message.sender_name,
        senderIp: message.sender_ip,
        isBot: !!message.sender_is_bot,
        readBy: [] as number[],
        reactions: [] as any[],
        replyTo: getReplyTo(message.reply_to),
      };

      io.to(`room:${roomId}`).emit('new_message', messageData);
      dispatchWebhooks('new_message', roomId, messageData);

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

    // Edit message
    socket.on('edit_message', (data) => {
      const { messageId, content } = data;

      // Verify ownership
      const message = queryOne('SELECT sender_id FROM messages WHERE id = ?', [messageId]);
      if (!message || message.sender_id !== userId) return;

      run("UPDATE messages SET content = ?, is_edited = 1, updated_at = datetime('now') WHERE id = ?", [content, messageId]);

      const updated = queryOne('SELECT updated_at FROM messages WHERE id = ?', [messageId]);
      const msg = queryOne('SELECT room_id FROM messages WHERE id = ?', [messageId]);

      const editPayload = { messageId, content, updatedAt: updated.updated_at };
      io.to(`room:${msg.room_id}`).emit('message_edited', editPayload);
      dispatchWebhooks('message_edited', msg.room_id, editPayload);
    });

    // Delete message
    socket.on('delete_message', (data) => {
      const { messageId } = data;

      // Verify ownership
      const message = queryOne('SELECT sender_id, room_id FROM messages WHERE id = ?', [messageId]);
      if (!message || message.sender_id !== userId) return;

      run("UPDATE messages SET is_deleted = 1, content = '', updated_at = datetime('now') WHERE id = ?", [messageId]);

      io.to(`room:${message.room_id}`).emit('message_deleted', { messageId });
      dispatchWebhooks('message_deleted', message.room_id, { messageId });
    });

    // Read receipt
    socket.on('read_receipt', (data) => {
      const { messageId, roomId } = data;

      run('INSERT OR IGNORE INTO read_receipts (message_id, user_id) VALUES (?, ?)', [messageId, userId]);

      io.to(`room:${roomId}`).emit('message_read', { messageId, userId, roomId });
    });

    // Typing indicators
    socket.on('typing_start', (roomId: number) => {
      const user = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
      socket.to(`room:${roomId}`).emit('user_typing', {
        roomId,
        userId,
        userName: user?.name || 'Unknown',
      });
    });

    socket.on('typing_stop', (roomId: number) => {
      socket.to(`room:${roomId}`).emit('user_stop_typing', { roomId, userId });
    });

    // Toggle reaction (add if not exists, remove if exists)
    socket.on('toggle_reaction', (data) => {
      const { messageId, roomId, emoji } = data;
      const existing = queryOne(
        'SELECT id FROM message_reactions WHERE message_id = ? AND user_id = ? AND emoji = ?',
        [messageId, userId, emoji],
      );
      if (existing) {
        run('DELETE FROM message_reactions WHERE id = ?', [existing.id]);
      } else {
        run('INSERT INTO message_reactions (message_id, user_id, emoji) VALUES (?, ?, ?)', [messageId, userId, emoji]);
      }
      const reactions = getReactionsForMessage(messageId);
      io.to(`room:${roomId}`).emit('reaction_updated', { messageId, roomId, reactions });
    });

    // Pin message
    socket.on('pin_message', (data) => {
      const { messageId, roomId } = data;
      const msg = queryOne('SELECT room_id FROM messages WHERE id = ?', [messageId]);
      if (!msg || msg.room_id !== roomId) return;

      const existing = queryOne('SELECT id FROM pinned_messages WHERE message_id = ?', [messageId]);
      if (existing) return;

      run('INSERT INTO pinned_messages (message_id, room_id, pinned_by) VALUES (?, ?, ?)', [messageId, roomId, userId]);

      const fullMsg = queryOne(
        `SELECT m.*, u.name as sender_name, u.ip as sender_ip, u.is_bot as sender_is_bot
         FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.id = ?`,
        [messageId],
      );
      const pinner = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
      const readBy = queryAll('SELECT user_id FROM read_receipts WHERE message_id = ?', [messageId]);

      const pin = {
        id: 0,
        messageId,
        roomId,
        pinnedBy: userId,
        pinnedByName: pinner?.name || 'Unknown',
        pinnedAt: new Date().toISOString(),
        message: {
          id: fullMsg.id,
          roomId: fullMsg.room_id,
          senderId: fullMsg.sender_id,
          content: fullMsg.is_deleted ? '' : fullMsg.content,
          type: fullMsg.type,
          fileUrl: fullMsg.is_deleted ? null : fullMsg.file_url,
          fileName: fullMsg.is_deleted ? null : fullMsg.file_name,
          fileSize: fullMsg.is_deleted ? null : fullMsg.file_size,
          isEdited: !!fullMsg.is_edited,
          isDeleted: !!fullMsg.is_deleted,
          mentions: fullMsg.mentions,
          replyToId: fullMsg.reply_to || null,
          createdAt: fullMsg.created_at,
          updatedAt: fullMsg.updated_at,
          senderName: fullMsg.sender_name,
          senderIp: fullMsg.sender_ip,
          isBot: !!fullMsg.sender_is_bot,
          readBy: readBy.map((r: any) => r.user_id),
          reactions: getReactionsForMessage(messageId),
          replyTo: getReplyTo(fullMsg.reply_to),
        },
      };
      io.to(`room:${roomId}`).emit('message_pinned', { roomId, pin });
    });

    // Unpin message
    socket.on('unpin_message', (data) => {
      const { messageId, roomId } = data;
      run('DELETE FROM pinned_messages WHERE message_id = ? AND room_id = ?', [messageId, roomId]);
      io.to(`room:${roomId}`).emit('message_unpinned', { roomId, messageId });
    });

    // Leave room permanently and delete all messages in the room
    socket.on('leave_room_permanent', (roomId: number) => {
      const user = queryOne('SELECT name FROM users WHERE id = ?', [userId]);
      const userName = user?.name || 'Unknown';

      run('DELETE FROM read_receipts WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)', [roomId]);
      run('DELETE FROM message_reactions WHERE message_id IN (SELECT id FROM messages WHERE room_id = ?)', [roomId]);
      run('DELETE FROM pinned_messages WHERE room_id = ?', [roomId]);
      run('DELETE FROM messages WHERE room_id = ?', [roomId]);
      run('DELETE FROM room_members WHERE room_id = ? AND user_id = ?', [roomId, userId]);

      socket.leave(`room:${roomId}`);

      io.to(`room:${roomId}`).emit('room_messages_cleared', { roomId, userId, userName });
      io.to(`room:${roomId}`).emit('member_left', { roomId, userId, userName });
    });

    // Disconnect
    socket.on('disconnect', () => {
      const uid = socketUserMap.get(socket.id);
      if (uid !== undefined) {
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

export function getOnlineUsers(): number[] {
  return Array.from(onlineUsers.keys());
}
