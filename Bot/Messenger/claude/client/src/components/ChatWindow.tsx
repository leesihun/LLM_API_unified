import { useState, useEffect, useRef, useCallback } from 'react';
import { useSocket } from '../contexts/SocketContext';
import api, { getServerUrl } from '../services/api';
import MessageBubble from './MessageBubble';
import MentionSuggestion from './MentionSuggestion';
import type { User, RoomWithDetails, MessageWithSender } from '../../../shared/types';

interface ChatWindowProps {
  room: RoomWithDetails;
  user: User;
  users: User[];
  onlineUserIds: Set<number>;
}

export default function ChatWindow({ room, user, users, onlineUserIds }: ChatWindowProps) {
  const { socket } = useSocket();
  const [messages, setMessages] = useState<MessageWithSender[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [typingUsers, setTypingUsers] = useState<Map<number, string>>(new Map());
  const [editingMessageId, setEditingMessageId] = useState<number | null>(null);
  const [editContent, setEditContent] = useState('');
  const [showMention, setShowMention] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionIndex, setMentionIndex] = useState(0);
  const [clipboardPreview, setClipboardPreview] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasMoreRef = useRef(true);
  const loadingMoreRef = useRef(false);
  const messagesContainerRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  // Fetch messages when room changes
  useEffect(() => {
    let cancelled = false;

    async function fetchMessages() {
      setLoading(true);
      setMessages([]);
      hasMoreRef.current = true;
      try {
        const res = await api.get(`/rooms/${room.id}/messages?userId=${user.id}`);
        if (!cancelled) {
          setMessages(res.data);
          setTimeout(scrollToBottom, 100);
        }
      } catch (err) {
        console.error('Failed to fetch messages:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchMessages();
    socket?.emit('join_room', room.id);

    return () => {
      cancelled = true;
    };
  }, [room.id, user.id, socket, scrollToBottom]);

  // Load more messages on scroll up
  const handleScroll = useCallback(async () => {
    const container = messagesContainerRef.current;
    if (!container || container.scrollTop > 50 || !hasMoreRef.current || loadingMoreRef.current) return;

    loadingMoreRef.current = true;
    const oldScrollHeight = container.scrollHeight;

    try {
      const firstMessageId = messages[0]?.id;
      if (!firstMessageId) return;

      const res = await api.get(`/rooms/${room.id}/messages?userId=${user.id}&before=${firstMessageId}`);
      if (res.data.length === 0) {
        hasMoreRef.current = false;
        return;
      }

      setMessages((prev) => [...res.data, ...prev]);

      // Maintain scroll position
      requestAnimationFrame(() => {
        if (container) {
          container.scrollTop = container.scrollHeight - oldScrollHeight;
        }
      });
    } catch (err) {
      console.error('Failed to load more messages:', err);
    } finally {
      loadingMoreRef.current = false;
    }
  }, [messages, room.id, user.id]);

  // Socket event listeners for messages
  useEffect(() => {
    if (!socket) return;

    const handleNewMessage = (message: MessageWithSender) => {
      if (message.roomId !== room.id) return;
      setMessages((prev) => {
        if (prev.some((m) => m.id === message.id)) return prev;
        return [...prev, message];
      });
      setTimeout(scrollToBottom, 50);

      // Send read receipt
      if (message.senderId !== user.id) {
        socket.emit('read_receipt', { messageId: message.id, roomId: room.id });
      }
    };

    const handleMessageEdited = (data: { messageId: number; content: string; updatedAt: string }) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === data.messageId ? { ...m, content: data.content, isEdited: true, updatedAt: data.updatedAt } : m
        )
      );
    };

    const handleMessageDeleted = (data: { messageId: number }) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === data.messageId ? { ...m, isDeleted: true, content: '' } : m
        )
      );
    };

    const handleMessageRead = (data: { messageId: number; userId: number }) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === data.messageId
            ? { ...m, readBy: [...(m.readBy || []), data.userId].filter((v, i, a) => a.indexOf(v) === i) }
            : m
        )
      );
    };

    const handleTyping = (data: { roomId: number; userId: number; userName: string }) => {
      if (data.roomId !== room.id || data.userId === user.id) return;
      setTypingUsers((prev) => new Map(prev).set(data.userId, data.userName));
    };

    const handleStopTyping = (data: { roomId: number; userId: number }) => {
      if (data.roomId !== room.id) return;
      setTypingUsers((prev) => {
        const next = new Map(prev);
        next.delete(data.userId);
        return next;
      });
    };

    socket.on('new_message', handleNewMessage);
    socket.on('message_edited', handleMessageEdited);
    socket.on('message_deleted', handleMessageDeleted);
    socket.on('message_read', handleMessageRead);
    socket.on('user_typing', handleTyping);
    socket.on('user_stop_typing', handleStopTyping);

    return () => {
      socket.off('new_message', handleNewMessage);
      socket.off('message_edited', handleMessageEdited);
      socket.off('message_deleted', handleMessageDeleted);
      socket.off('message_read', handleMessageRead);
      socket.off('user_typing', handleTyping);
      socket.off('user_stop_typing', handleStopTyping);
    };
  }, [socket, room.id, user.id, scrollToBottom]);

  // Send read receipts for visible messages
  useEffect(() => {
    if (!socket || messages.length === 0) return;

    const unread = messages.filter(
      (m) => m.senderId !== user.id && !(m.readBy || []).includes(user.id)
    );

    for (const msg of unread) {
      socket.emit('read_receipt', { messageId: msg.id, roomId: room.id });
    }
  }, [socket, messages, room.id, user.id]);

  // Handle input change with mention detection
  const handleInputChange = (value: string) => {
    setInput(value);

    // Detect @mention
    const cursorPos = inputRef.current?.selectionStart || value.length;
    const textBeforeCursor = value.slice(0, cursorPos);
    const mentionMatch = textBeforeCursor.match(/@(\w*)$/);

    if (mentionMatch) {
      setShowMention(true);
      setMentionQuery(mentionMatch[1]);
      setMentionIndex(0);
    } else {
      setShowMention(false);
    }

    // Typing indicator
    socket?.emit('typing_start', room.id);
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
    typingTimeoutRef.current = setTimeout(() => {
      socket?.emit('typing_stop', room.id);
    }, 2000);
  };

  // Get filtered mention users
  const mentionUsers = room.members.filter(
    (m) => m.id !== user.id && m.name.toLowerCase().includes(mentionQuery.toLowerCase())
  );

  // Insert mention
  const insertMention = (mentionUser: User) => {
    const cursorPos = inputRef.current?.selectionStart || input.length;
    const textBeforeCursor = input.slice(0, cursorPos);
    const textAfterCursor = input.slice(cursorPos);
    const newBefore = textBeforeCursor.replace(/@\w*$/, `@${mentionUser.name} `);

    setInput(newBefore + textAfterCursor);
    setShowMention(false);
    inputRef.current?.focus();
  };

  // Send message
  const sendMessage = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || !socket) return;

    // Extract mentions
    const mentionMatches = trimmed.match(/@(\S+)/g) || [];
    const mentionedIds = mentionMatches
      .map((m) => m.slice(1))
      .map((name) => room.members.find((u) => u.name === name)?.id)
      .filter((id): id is number => id !== undefined);

    socket.emit('send_message', {
      roomId: room.id,
      content: trimmed,
      type: 'text',
      mentions: mentionedIds,
    });

    setInput('');
    socket.emit('typing_stop', room.id);
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
  }, [input, socket, room]);

  // Handle keyboard events
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMention && mentionUsers.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex((prev) => Math.min(prev + 1, mentionUsers.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault();
        insertMention(mentionUsers[mentionIndex]);
        return;
      }
      if (e.key === 'Escape') {
        setShowMention(false);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Clipboard paste (Ctrl+V image)
  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;

    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) return;

        const reader = new FileReader();
        reader.onload = () => {
          setClipboardPreview(reader.result as string);
        };
        reader.readAsDataURL(file);
        return;
      }
    }
  };

  // Send clipboard image
  const sendClipboardImage = async () => {
    if (!clipboardPreview || !socket) return;

    try {
      const res = await api.post('/upload/image-base64', {
        data: clipboardPreview,
        fileName: 'clipboard-image.png',
      });

      socket.emit('send_message', {
        roomId: room.id,
        content: '',
        type: 'image',
        fileUrl: res.data.fileUrl,
        fileName: res.data.fileName,
        fileSize: res.data.fileSize,
      });

      setClipboardPreview(null);
    } catch (err) {
      console.error('Failed to upload clipboard image:', err);
    }
  };

  // File upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !socket) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await api.post('/upload/file', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      const isImage = file.type.startsWith('image/');
      socket.emit('send_message', {
        roomId: room.id,
        content: '',
        type: isImage ? 'image' : 'file',
        fileUrl: res.data.fileUrl,
        fileName: res.data.fileName,
        fileSize: res.data.fileSize,
      });
    } catch (err) {
      console.error('Failed to upload file:', err);
    }

    e.target.value = '';
  };

  // Edit message
  const handleEditMessage = (messageId: number, content: string) => {
    setEditingMessageId(messageId);
    setEditContent(content);
  };

  const submitEdit = () => {
    if (!editingMessageId || !socket) return;
    socket.emit('edit_message', { messageId: editingMessageId, content: editContent });
    setEditingMessageId(null);
    setEditContent('');
  };

  // Delete message
  const handleDeleteMessage = (messageId: number) => {
    socket?.emit('delete_message', { messageId });
  };

  const typingText = (() => {
    const names = Array.from(typingUsers.values());
    if (names.length === 0) return null;
    if (names.length === 1) return `${names[0]}님이 입력 중...`;
    return `${names.join(', ')}님이 입력 중...`;
  })();

  const getDisplayName = () => {
    if (room.isGroup) return room.name;
    const other = room.members.find((m) => m.id !== user.id);
    return other?.name || room.name;
  };

  const isOtherOnline = () => {
    if (room.isGroup) return room.members.some((m) => m.id !== user.id && onlineUserIds.has(m.id));
    const other = room.members.find((m) => m.id !== user.id);
    return other ? onlineUserIds.has(other.id) : false;
  };

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Chat Header */}
      <div className="px-6 py-4 bg-white border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-medium ${
            room.isGroup ? 'bg-purple-500' : 'bg-blue-500'
          }`}>
            {room.isGroup ? '👥' : getDisplayName().charAt(0).toUpperCase()}
          </div>
          <div>
            <h2 className="font-semibold text-gray-800">{getDisplayName()}</h2>
            <p className="text-xs text-gray-400">
              {room.isGroup
                ? `${room.members.length}명 참여`
                : isOtherOnline()
                  ? '온라인'
                  : '오프라인'}
            </p>
          </div>
        </div>
        {room.isGroup && (
          <div className="text-xs text-gray-400">
            {room.members.map((m) => m.name).join(', ')}
          </div>
        )}
      </div>

      {/* Messages */}
      <div
        ref={messagesContainerRef}
        className="flex-1 overflow-y-auto px-6 py-4 space-y-1"
        onScroll={handleScroll}
      >
        {loading ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            메시지 로딩 중...
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isOwn={msg.senderId === user.id}
                currentUserId={user.id}
                roomMembers={room.members}
                editingMessageId={editingMessageId}
                editContent={editContent}
                onEditContentChange={setEditContent}
                onSubmitEdit={submitEdit}
                onCancelEdit={() => { setEditingMessageId(null); setEditContent(''); }}
                onEdit={handleEditMessage}
                onDelete={handleDeleteMessage}
                serverUrl={getServerUrl()}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Typing indicator */}
      {typingText && (
        <div className="px-6 py-1 text-xs text-gray-400 italic">{typingText}</div>
      )}

      {/* Clipboard Preview */}
      {clipboardPreview && (
        <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
          <div className="flex items-center gap-3">
            <img
              src={clipboardPreview}
              alt="clipboard preview"
              className="w-20 h-20 object-cover rounded border"
            />
            <div className="flex-1">
              <p className="text-sm text-gray-600">클립보드 이미지를 전송하시겠습니까?</p>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={sendClipboardImage}
                  className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
                >
                  전송
                </button>
                <button
                  onClick={() => setClipboardPreview(null)}
                  className="px-3 py-1 bg-gray-300 text-gray-700 text-sm rounded hover:bg-gray-400"
                >
                  취소
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-6 py-4 bg-white border-t border-gray-200">
        <div className="relative">
          {showMention && mentionUsers.length > 0 && (
            <MentionSuggestion
              users={mentionUsers}
              selectedIndex={mentionIndex}
              onSelect={insertMention}
            />
          )}
          <div className="flex items-end gap-2">
            {/* File upload */}
            <label className="cursor-pointer flex-shrink-0 text-gray-400 hover:text-gray-600 p-2">
              <input type="file" className="hidden" onChange={handleFileUpload} />
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </label>

            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder="메시지를 입력하세요... (@으로 멘션)"
              rows={1}
              className="flex-1 resize-none px-4 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none text-sm max-h-32"
              style={{ minHeight: '40px' }}
            />

            <button
              onClick={sendMessage}
              disabled={!input.trim()}
              className="flex-shrink-0 bg-blue-600 text-white p-2.5 rounded-xl hover:bg-blue-700 transition disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
