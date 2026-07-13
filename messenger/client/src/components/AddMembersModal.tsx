import { useState } from 'react';
import api from '../services/api';
import type { RoomWithDetails, User } from '../../../shared/types';

interface AddMembersModalProps {
  room: RoomWithDetails;
  currentUser: User;
  users: User[];
  onClose: () => void;
  onAdded: () => void;
}

export default function AddMembersModal({ room, currentUser, users, onClose, onAdded }: AddMembersModalProps) {
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Only users not already in the room can be added.
  const memberIds = new Set(room.members.map((m) => m.id));
  const candidates = users.filter((u) => !memberIds.has(u.id));

  const toggleUser = (userId: number) => {
    setSelectedUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const handleAdd = async () => {
    if (selectedUserIds.length === 0) {
      setError('추가할 사용자를 선택해주세요.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await api.post(`/rooms/${room.id}/members`, {
        memberIds: selectedUserIds,
        userId: currentUser.id,
      });
      onAdded();
    } catch (err: any) {
      setError(err.response?.data?.error || '사용자 추가에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-gray-800 mb-1">사용자 추가</h2>
        <p className="text-sm text-gray-400 mb-4">이 채팅방에 초대할 사용자를 선택하세요.</p>

        <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-lg mb-4">
          {candidates.length === 0 ? (
            <div className="p-4 text-center text-gray-400 text-sm">
              추가할 수 있는 사용자가 없습니다.
            </div>
          ) : (
            candidates.map((u) => (
              <label
                key={u.id}
                className={`flex items-center gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer border-b border-gray-100 last:border-0 ${
                  selectedUserIds.includes(u.id) ? 'bg-blue-50' : ''
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedUserIds.includes(u.id)}
                  onChange={() => toggleUser(u.id)}
                  className="accent-blue-600"
                />
                <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center text-white text-sm font-medium">
                  {u.name.charAt(0).toUpperCase()}
                </div>
                <span className="text-sm text-gray-700">
                  {u.name}
                  {u.isBot ? ' (BOT)' : ''}
                </span>
              </label>
            ))
          )}
        </div>

        {error && (
          <div className="bg-red-50 text-red-600 px-3 py-2 rounded-lg text-sm mb-4">{error}</div>
        )}

        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition text-sm font-medium"
          >
            취소
          </button>
          <button
            onClick={handleAdd}
            disabled={loading || candidates.length === 0}
            className="flex-1 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-medium disabled:opacity-50"
          >
            {loading ? '추가 중...' : '추가'}
          </button>
        </div>
      </div>
    </div>
  );
}
