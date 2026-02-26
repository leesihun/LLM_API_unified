import { useState } from 'react';
import type { MessageWithSender, User } from '../../../shared/types';

interface MessageBubbleProps {
  message: MessageWithSender;
  isOwn: boolean;
  currentUserId: number;
  roomMembers: User[];
  editingMessageId: number | null;
  editContent: string;
  onEditContentChange: (content: string) => void;
  onSubmitEdit: () => void;
  onCancelEdit: () => void;
  onEdit: (messageId: number, content: string) => void;
  onDelete: (messageId: number) => void;
  serverUrl: string;
}

export default function MessageBubble({
  message,
  isOwn,
  currentUserId,
  roomMembers,
  editingMessageId,
  editContent,
  onEditContentChange,
  onSubmitEdit,
  onCancelEdit,
  onEdit,
  onDelete,
  serverUrl,
}: MessageBubbleProps) {
  const [showMenu, setShowMenu] = useState(false);

  const isEditing = editingMessageId === message.id;

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr + 'Z');
    return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  };

  // Render content with @mention highlights
  const renderContent = (content: string) => {
    if (!content) return null;
    const parts = content.split(/(@\S+)/g);
    return parts.map((part, i) => {
      if (part.startsWith('@')) {
        const name = part.slice(1);
        const isMentioned = roomMembers.some((m) => m.name === name);
        if (isMentioned) {
          return (
            <span key={i} className="mention-highlight">
              {part}
            </span>
          );
        }
      }
      return <span key={i}>{part}</span>;
    });
  };

  // Read count
  const readCount = (message.readBy || []).filter((id) => id !== message.senderId).length;
  const totalOthers = roomMembers.length - 1;
  const allRead = readCount >= totalOthers && totalOthers > 0;

  if (message.isDeleted) {
    return (
      <div className={`flex ${isOwn ? 'justify-end' : 'justify-start'} mb-1`}>
        <div className="max-w-[70%]">
          {!isOwn && (
            <span className="text-xs text-gray-400 ml-1">{message.senderName}</span>
          )}
          <div className="px-4 py-2 rounded-2xl bg-gray-100 text-gray-400 italic text-sm">
            삭제된 메시지입니다.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`flex ${isOwn ? 'justify-end' : 'justify-start'} mb-1 group`}
      onMouseLeave={() => setShowMenu(false)}
    >
      <div className={`max-w-[70%] ${isOwn ? 'items-end' : 'items-start'}`}>
        {/* Sender name (for others) */}
        {!isOwn && (
          <span className="text-xs text-gray-400 ml-1 block mb-0.5">{message.senderName}</span>
        )}

        <div className="flex items-end gap-1">
          {/* Menu (for own messages) */}
          {isOwn && (
            <div className="relative flex items-center">
              {/* Read status */}
              <span className={`text-xs mr-1 ${allRead ? 'text-blue-500' : 'text-gray-300'}`}>
                {readCount > 0 ? `✓${readCount}` : ''}
              </span>

              <span className="text-xs text-gray-300 mr-1">{formatTime(message.createdAt)}</span>

              <button
                onClick={() => setShowMenu(!showMenu)}
                className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-gray-500 transition text-xs p-1"
              >
                ⋮
              </button>
              {showMenu && (
                <div className="absolute bottom-full right-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-10 min-w-[80px]">
                  {message.type === 'text' && (
                    <button
                      onClick={() => { onEdit(message.id, message.content); setShowMenu(false); }}
                      className="block w-full text-left px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
                    >
                      수정
                    </button>
                  )}
                  <button
                    onClick={() => { onDelete(message.id); setShowMenu(false); }}
                    className="block w-full text-left px-3 py-1.5 text-sm text-red-500 hover:bg-gray-100"
                  >
                    삭제
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Message bubble */}
          <div
            className={`px-4 py-2 rounded-2xl text-sm ${
              isOwn
                ? 'bg-blue-600 text-white rounded-br-md'
                : 'bg-white text-gray-800 border border-gray-200 rounded-bl-md'
            }`}
          >
            {isEditing ? (
              <div className="space-y-2">
                <textarea
                  value={editContent}
                  onChange={(e) => onEditContentChange(e.target.value)}
                  className="w-full p-2 text-sm border rounded text-gray-800 resize-none"
                  rows={2}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      onSubmitEdit();
                    }
                    if (e.key === 'Escape') onCancelEdit();
                  }}
                />
                <div className="flex gap-1 justify-end">
                  <button onClick={onCancelEdit} className="text-xs px-2 py-1 bg-gray-200 text-gray-600 rounded">
                    취소
                  </button>
                  <button onClick={onSubmitEdit} className="text-xs px-2 py-1 bg-blue-500 text-white rounded">
                    저장
                  </button>
                </div>
              </div>
            ) : (
              <>
                {message.type === 'text' && (
                  <p className="whitespace-pre-wrap break-words">{renderContent(message.content)}</p>
                )}
                {message.type === 'image' && message.fileUrl && (
                  <div>
                    <img
                      src={`${serverUrl}${message.fileUrl}`}
                      alt={message.fileName || 'image'}
                      className="max-w-full rounded-lg cursor-pointer max-h-64"
                      onClick={() => window.open(`${serverUrl}${message.fileUrl}`, '_blank')}
                    />
                    {message.content && (
                      <p className="mt-1 whitespace-pre-wrap break-words">{renderContent(message.content)}</p>
                    )}
                  </div>
                )}
                {message.type === 'file' && message.fileUrl && (
                  <a
                    href={`${serverUrl}${message.fileUrl}`}
                    download={message.fileName}
                    className={`flex items-center gap-2 ${isOwn ? 'text-white hover:text-blue-100' : 'text-blue-600 hover:text-blue-800'}`}
                  >
                    <span>📎</span>
                    <span className="underline">{message.fileName || '파일 다운로드'}</span>
                    {message.fileSize && (
                      <span className="text-xs opacity-70">
                        ({(message.fileSize / 1024 / 1024).toFixed(1)}MB)
                      </span>
                    )}
                  </a>
                )}
                {message.type !== 'text' && !message.fileUrl && (
                  <p className="text-gray-400 italic">파일이 만료되었습니다.</p>
                )}
                {message.isEdited && (
                  <span className={`text-xs ${isOwn ? 'text-blue-200' : 'text-gray-400'}`}> (수정됨)</span>
                )}
              </>
            )}
          </div>

          {/* Time + read (for others' messages) */}
          {!isOwn && (
            <span className="text-xs text-gray-300 ml-1">{formatTime(message.createdAt)}</span>
          )}
        </div>
      </div>
    </div>
  );
}
