import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useSocket } from '../contexts/SocketContext';
import api from '../services/api';
import Sidebar from '../components/Sidebar';
import ChatWindow from '../components/ChatWindow';
import NewRoomModal from '../components/NewRoomModal';
import { showNotification } from '../utils/notifications';
import type { RoomWithDetails, User } from '../../../shared/types';

export default function ChatPage() {
  const { user, logout } = useAuth();
  const { socket, connected } = useSocket();
  const [rooms, setRooms] = useState<RoomWithDetails[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState<number | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [onlineUserIds, setOnlineUserIds] = useState<Set<number>>(new Set());
  const [silentMode, setSilentMode] = useState(() => localStorage.getItem('huni_silent') === 'true');
  const [showNewRoom, setShowNewRoom] = useState(false);

  const selectedRoom = rooms.find((r) => r.id === selectedRoomId) || null;

  // Fetch rooms
  const fetchRooms = useCallback(async () => {
    if (!user) return;
    try {
      const res = await api.get(`/rooms?userId=${user.id}`);
      setRooms(res.data);
    } catch (err) {
      console.error('Failed to fetch rooms:', err);
    }
  }, [user]);

  // Fetch users
  const fetchUsers = useCallback(async () => {
    try {
      const res = await api.get('/auth/users');
      setUsers(res.data);
    } catch (err) {
      console.error('Failed to fetch users:', err);
    }
  }, []);

  useEffect(() => {
    fetchRooms();
    fetchUsers();
  }, [fetchRooms, fetchUsers]);

  // Socket event listeners
  useEffect(() => {
    if (!socket || !user) return;

    const handleNewMessage = (message: any) => {
      setRooms((prev) =>
        prev
          .map((room) => {
            if (room.id === message.roomId) {
              return {
                ...room,
                lastMessage: message,
                unreadCount: message.senderId === user.id
                  ? room.unreadCount
                  : selectedRoomId === room.id
                    ? room.unreadCount
                    : room.unreadCount + 1,
              };
            }
            return room;
          })
          .sort((a, b) => {
            const aTime = a.lastMessage?.createdAt || a.createdAt;
            const bTime = b.lastMessage?.createdAt || b.createdAt;
            return bTime.localeCompare(aTime);
          })
      );

      // Desktop notification
      if (message.senderId !== user.id && !silentMode && selectedRoomId !== message.roomId) {
        const senderRoom = rooms.find((r) => r.id === message.roomId);
        const title = senderRoom?.isGroup
          ? `${message.senderName} (${senderRoom.name})`
          : message.senderName;
        const body = message.type === 'text'
          ? message.content
          : message.type === 'image'
            ? '이미지를 보냈습니다.'
            : '파일을 보냈습니다.';

        showNotification(title, body);
      }
    };

    const handleMentionNotification = (data: any) => {
      if (!silentMode) {
        showNotification(
          `@멘션 - ${data.roomName || data.message.senderName}`,
          `${data.message.senderName}님이 회원님을 멘션했습니다.`
        );
      }
    };

    const handleOnlineStatus = (data: { userId: number; online: boolean }) => {
      setOnlineUserIds((prev) => {
        const next = new Set(prev);
        if (data.online) next.add(data.userId);
        else next.delete(data.userId);
        return next;
      });
    };

    const handleRoomCreated = (room: RoomWithDetails) => {
      setRooms((prev) => {
        if (prev.some((r) => r.id === room.id)) return prev;
        return [room, ...prev];
      });
      // Auto-join the new room via socket
      socket.emit('join_room', room.id);
    };

    const handleMemberLeft = (data: { roomId: number; userId: number }) => {
      setRooms((prev) =>
        prev.map((room) =>
          room.id === data.roomId
            ? { ...room, members: room.members.filter((m) => m.id !== data.userId) }
            : room
        )
      );
    };

    const handleMessagesCleared = (data: { roomId: number }) => {
      setRooms((prev) =>
        prev.map((room) =>
          room.id === data.roomId
            ? { ...room, lastMessage: null, unreadCount: 0 }
            : room
        )
      );
    };

    socket.on('new_message', handleNewMessage);
    socket.on('mention_notification', handleMentionNotification);
    socket.on('user_online_status', handleOnlineStatus);
    socket.on('room_created', handleRoomCreated);
    socket.on('member_left', handleMemberLeft);
    socket.on('room_messages_cleared', handleMessagesCleared);

    return () => {
      socket.off('new_message', handleNewMessage);
      socket.off('mention_notification', handleMentionNotification);
      socket.off('user_online_status', handleOnlineStatus);
      socket.off('room_created', handleRoomCreated);
      socket.off('member_left', handleMemberLeft);
      socket.off('room_messages_cleared', handleMessagesCleared);
    };
  }, [socket, user, silentMode, selectedRoomId, rooms]);

  const toggleSilent = () => {
    const next = !silentMode;
    setSilentMode(next);
    localStorage.setItem('huni_silent', String(next));
  };

  const handleRoomCreated = async () => {
    setShowNewRoom(false);
    await fetchRooms();
  };

  const handleSelectRoom = (roomId: number) => {
    setSelectedRoomId(roomId);
    // Reset unread count
    setRooms((prev) =>
      prev.map((r) => (r.id === roomId ? { ...r, unreadCount: 0 } : r))
    );
  };

  if (!user) return null;

  return (
    <div className="flex h-screen bg-gray-100">
      {/* Sidebar */}
      <Sidebar
        rooms={rooms}
        selectedRoomId={selectedRoomId}
        onSelectRoom={handleSelectRoom}
        onNewRoom={() => setShowNewRoom(true)}
        user={user}
        onlineUserIds={onlineUserIds}
        connected={connected}
        silentMode={silentMode}
        onToggleSilent={toggleSilent}
        onLogout={logout}
      />

      {/* Chat Window */}
      <div className="flex-1 flex flex-col">
        {selectedRoom ? (
          <ChatWindow
            room={selectedRoom}
            user={user}
            users={users}
            onlineUserIds={onlineUserIds}
            onLeaveRoom={(roomId) => {
              setRooms((prev) => prev.filter((r) => r.id !== roomId));
              setSelectedRoomId(null);
            }}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <div className="text-6xl mb-4">💬</div>
              <p className="text-xl">채팅방을 선택하세요</p>
            </div>
          </div>
        )}
      </div>

      {/* New Room Modal */}
      {showNewRoom && (
        <NewRoomModal
          users={users}
          currentUser={user}
          onClose={() => setShowNewRoom(false)}
          onCreated={handleRoomCreated}
        />
      )}
    </div>
  );
}
