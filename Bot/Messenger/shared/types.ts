// ===== DB Models =====

export interface User {
  id: number;
  ip: string;
  name: string;
  isBot?: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface Room {
  id: number;
  name: string;
  isGroup: boolean;
  createdBy: number;
  createdAt: string;
}

export interface RoomMember {
  id: number;
  roomId: number;
  userId: number;
  joinedAt: string;
}

export interface Message {
  id: number;
  roomId: number;
  senderId: number;
  content: string;
  type: 'text' | 'image' | 'file';
  fileUrl: string | null;
  fileName: string | null;
  fileSize: number | null;
  isEdited: boolean;
  isDeleted: boolean;
  mentions: string; // JSON array of user IDs
  replyToId: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface ReadReceipt {
  id: number;
  messageId: number;
  userId: number;
  readAt: string;
}

export interface MessageReaction {
  emoji: string;
  userIds: number[];
  userNames: string[];
}

export interface PinnedMessage {
  id: number;
  messageId: number;
  roomId: number;
  pinnedBy: number;
  pinnedByName: string;
  pinnedAt: string;
  message: MessageWithSender;
}

// ===== API Types =====

export interface LoginRequest {
  name: string;
}

export interface LoginResponse {
  user: User;
}

export interface CreateRoomRequest {
  name: string;
  isGroup: boolean;
  memberIds: number[];
}

export interface MessageWithSender extends Message {
  senderName: string;
  senderIp: string;
  readBy: number[];
  reactions: MessageReaction[];
  replyTo: MessageWithSender | null;
}

export interface RoomWithDetails extends Room {
  members: User[];
  lastMessage: MessageWithSender | null;
  unreadCount: number;
}

// ===== Bridge Types (LLM Agent Integration) =====

export interface ApiKey {
  id: number;
  userId: number;
  label: string;
  isActive: boolean;
  createdAt: string;
  lastUsedAt: string | null;
}

export interface Webhook {
  id: number;
  url: string;
  roomId: number | null;
  events: string[];
  isActive: boolean;
  createdBy: number;
  createdAt: string;
}

export interface WebWatcher {
  id: number;
  url: string;
  roomId: number;
  senderId: number;
  intervalSeconds: number;
  isActive: boolean;
  lastCheckedAt: string | null;
  lastChangedAt: string | null;
  createdAt: string;
}

// ===== Socket.IO Events =====

export interface ClientToServerEvents {
  join_room: (roomId: number) => void;
  leave_room: (roomId: number) => void;
  send_message: (data: {
    roomId: number;
    content: string;
    type: 'text' | 'image' | 'file';
    fileUrl?: string;
    fileName?: string;
    fileSize?: number;
    mentions?: number[];
    replyToId?: number;
  }) => void;
  edit_message: (data: { messageId: number; content: string }) => void;
  delete_message: (data: { messageId: number }) => void;
  read_receipt: (data: { messageId: number; roomId: number }) => void;
  typing_start: (roomId: number) => void;
  typing_stop: (roomId: number) => void;
  toggle_reaction: (data: { messageId: number; roomId: number; emoji: string }) => void;
  pin_message: (data: { messageId: number; roomId: number }) => void;
  unpin_message: (data: { messageId: number; roomId: number }) => void;
  leave_room_permanent: (roomId: number) => void;
}

export interface ServerToClientEvents {
  new_message: (message: MessageWithSender) => void;
  message_edited: (data: { messageId: number; content: string; updatedAt: string }) => void;
  message_deleted: (data: { messageId: number }) => void;
  message_read: (data: { messageId: number; userId: number; roomId: number }) => void;
  user_typing: (data: { roomId: number; userId: number; userName: string }) => void;
  user_stop_typing: (data: { roomId: number; userId: number }) => void;
  user_online_status: (data: { userId: number; online: boolean }) => void;
  room_created: (room: RoomWithDetails) => void;
  mention_notification: (data: { message: MessageWithSender; roomName: string }) => void;
  reaction_updated: (data: { messageId: number; roomId: number; reactions: MessageReaction[] }) => void;
  message_pinned: (data: { roomId: number; pin: PinnedMessage }) => void;
  message_unpinned: (data: { roomId: number; messageId: number }) => void;
  member_left: (data: { roomId: number; userId: number; userName: string }) => void;
  room_messages_cleared: (data: { roomId: number; userId: number; userName: string }) => void;
}
