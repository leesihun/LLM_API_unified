import type { RoomWithDetails, User } from '../../../shared/types';

interface SidebarProps {
  rooms: RoomWithDetails[];
  selectedRoomId: number | null;
  onSelectRoom: (roomId: number) => void;
  onNewRoom: () => void;
  user: User;
  onlineUserIds: Set<number>;
  connected: boolean;
  silentMode: boolean;
  onToggleSilent: () => void;
  onLogout: () => void;
}

export default function Sidebar({
  rooms,
  selectedRoomId,
  onSelectRoom,
  onNewRoom,
  user,
  onlineUserIds,
  connected,
  silentMode,
  onToggleSilent,
  onLogout,
}: SidebarProps) {
  const getDisplayName = (room: RoomWithDetails) => {
    if (room.isGroup) return room.name;
    const other = room.members.find((m) => m.id !== user.id);
    return other?.name || room.name;
  };

  const getLastMessagePreview = (room: RoomWithDetails) => {
    if (!room.lastMessage) return '';
    if (room.lastMessage.isDeleted) return '삭제된 메시지';
    if (room.lastMessage.type === 'image') return '🖼️ 이미지';
    if (room.lastMessage.type === 'file') return `📎 ${room.lastMessage.fileName || '파일'}`;
    return room.lastMessage.content;
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr + 'Z');
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    if (isToday) {
      return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
  };

  const isOtherOnline = (room: RoomWithDetails) => {
    if (room.isGroup) return room.members.some((m) => m.id !== user.id && onlineUserIds.has(m.id));
    const other = room.members.find((m) => m.id !== user.id);
    return other ? onlineUserIds.has(other.id) : false;
  };

  return (
    <div className="w-80 bg-white border-r border-gray-200 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-xl font-bold text-gray-800">Messenger</h1>
          <div className="flex items-center gap-1">
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600">{user.name}</span>
          <div className="flex items-center gap-2">
            <button
              onClick={onToggleSilent}
              className={`text-sm px-2 py-1 rounded ${silentMode ? 'bg-gray-200 text-gray-600' : 'bg-blue-100 text-blue-600'}`}
              title={silentMode ? '알림 꺼짐' : '알림 켜짐'}
            >
              {silentMode ? '🔇' : '🔔'}
            </button>
            <button
              onClick={onLogout}
              className="text-sm text-gray-400 hover:text-gray-600"
              title="로그아웃"
            >
              ↩
            </button>
          </div>
        </div>
      </div>

      {/* New Room Button */}
      <div className="p-3">
        <button
          onClick={onNewRoom}
          className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-medium"
        >
          + 새 채팅
        </button>
      </div>

      {/* Room List */}
      <div className="flex-1 overflow-y-auto">
        {rooms.length === 0 ? (
          <div className="p-4 text-center text-gray-400 text-sm">
            채팅방이 없습니다. 새 채팅을 시작하세요.
          </div>
        ) : (
          rooms.map((room) => (
            <div
              key={room.id}
              onClick={() => onSelectRoom(room.id)}
              className={`flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 transition ${
                selectedRoomId === room.id ? 'bg-blue-50 border-r-2 border-blue-500' : ''
              }`}
            >
              {/* Avatar */}
              <div className="relative flex-shrink-0">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-medium ${
                  room.isGroup ? 'bg-purple-500' : 'bg-blue-500'
                }`}>
                  {room.isGroup ? '👥' : getDisplayName(room).charAt(0).toUpperCase()}
                </div>
                {isOtherOnline(room) && (
                  <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-400 border-2 border-white rounded-full" />
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-800 truncate text-sm">
                    {getDisplayName(room)}
                    {room.isGroup && (
                      <span className="text-gray-400 ml-1 text-xs">{room.members.length}</span>
                    )}
                  </span>
                  {room.lastMessage && (
                    <span className="text-xs text-gray-400 flex-shrink-0 ml-2">
                      {formatTime(room.lastMessage.createdAt)}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-xs text-gray-500 truncate">
                    {getLastMessagePreview(room)}
                  </span>
                  {room.unreadCount > 0 && (
                    <span className="ml-2 bg-blue-500 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[20px] text-center flex-shrink-0">
                      {room.unreadCount > 99 ? '99+' : room.unreadCount}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
