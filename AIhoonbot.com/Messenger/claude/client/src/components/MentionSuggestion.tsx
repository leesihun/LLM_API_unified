import type { User } from '../../../shared/types';

interface MentionSuggestionProps {
  users: User[];
  selectedIndex: number;
  onSelect: (user: User) => void;
}

export default function MentionSuggestion({ users, selectedIndex, onSelect }: MentionSuggestionProps) {
  return (
    <div className="absolute bottom-full left-0 mb-2 bg-white border border-gray-200 rounded-lg shadow-lg py-1 max-h-40 overflow-y-auto w-56 z-20">
      {users.map((user, index) => (
        <button
          key={user.id}
          onClick={() => onSelect(user)}
          className={`block w-full text-left px-3 py-2 text-sm hover:bg-blue-50 ${
            index === selectedIndex ? 'bg-blue-50 text-blue-600' : 'text-gray-700'
          }`}
        >
          <span className="font-medium">@{user.name}</span>
        </button>
      ))}
    </div>
  );
}
