import { useState } from 'react';
import api from '../services/api';
import type { User } from '../../../shared/types';

interface NewRoomModalProps {
  users: User[];
  currentUser: User;
  onClose: () => void;
  onCreated: () => void;
}

export default function NewRoomModal({ users, currentUser, onClose, onCreated }: NewRoomModalProps) {
  const [isGroup, setIsGroup] = useState(false);
  const [groupName, setGroupName] = useState('');
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const otherUsers = users.filter((u) => u.id !== currentUser.id);

  const toggleUser = (userId: number) => {
    setSelectedUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const handleCreate = async () => {
    if (selectedUserIds.length === 0) {
      setError('대화 상대를 선택해주세요.');
      return;
    }
    if (isGroup && !groupName.trim()) {
      setError('그룹 이름을 입력해주세요.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await api.post('/rooms', {
        name: isGroup ? groupName.trim() : '',
        isGroup,
        memberIds: selectedUserIds,
        userId: currentUser.id,
      });
      onCreated();
    } catch (err: any) {
      setError(err.response?.data?.error || '채팅방 생성에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-gray-800 mb-4">새 채팅</h2>

        {/* Toggle 1:1 / Group */}
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => { setIsGroup(false); setSelectedUserIds([]); }}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
              !isGroup ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            1:1 채팅
          </button>
          <button
            onClick={() => setIsGroup(true)}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
              isGroup ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            그룹 채팅
          </button>
        </div>

        {/* Group name */}
        {isGroup && (
          <input
            type="text"
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
            placeholder="그룹 이름"
            className="w-full px-4 py-2.5 border border-gray-300 rounded-lg mb-4 outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
        )}

        {/* User list */}
        <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-lg mb-4">
          {otherUsers.length === 0 ? (
            <div className="p-4 text-center text-gray-400 text-sm">
              다른 사용자가 없습니다.
            </div>
          ) : (
            otherUsers.map((u) => (
              <label
                key={u.id}
                className={`flex items-center gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer border-b border-gray-100 last:border-0 ${
                  selectedUserIds.includes(u.id) ? 'bg-blue-50' : ''
                }`}
              >
                <input
                  type={isGroup ? 'checkbox' : 'radio'}
                  name="user"
                  checked={selectedUserIds.includes(u.id)}
                  onChange={() => {
                    if (!isGroup) {
                      setSelectedUserIds([u.id]);
                    } else {
                      toggleUser(u.id);
                    }
                  }}
                  className="accent-blue-600"
                />
                <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center text-white text-sm font-medium">
                  {u.name.charAt(0).toUpperCase()}
                </div>
                <span className="text-sm text-gray-700">{u.name}</span>
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
            onClick={handleCreate}
            disabled={loading}
            className="flex-1 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-medium disabled:opacity-50"
          >
            {loading ? '생성 중...' : '채팅 시작'}
          </button>
        </div>
      </div>
    </div>
  );
}
