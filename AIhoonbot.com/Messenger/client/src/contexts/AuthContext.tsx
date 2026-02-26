import React, { createContext, useContext, useState, useCallback } from 'react';
import api, { setServerUrl } from '../services/api';
import type { User } from '../../../shared/types';

interface AuthState {
  user: User | null;
  serverUrl: string;
  isConnected: boolean;
}

interface AuthContextType extends AuthState {
  login: (serverUrl: string, name: string) => Promise<void>;
  logout: () => void;
  checkExistingUser: (serverUrl: string) => Promise<User | null>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>(() => {
    // Always start with no user so the network settings screen shows first.
    // Restore only the serverUrl so the field is pre-filled.
    const saved = localStorage.getItem('huni_auth');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed.serverUrl) {
          setServerUrl(parsed.serverUrl);
        }
        return { user: null, serverUrl: parsed.serverUrl || '', isConnected: false };
      } catch {
        // ignore
      }
    }
    return { user: null, serverUrl: '', isConnected: false };
  });

  const login = useCallback(async (serverUrl: string, name: string) => {
    setServerUrl(serverUrl);
    const res = await api.post('/auth/login', { name });
    const user = res.data.user;
    const newState = { user, serverUrl, isConnected: true };
    setState(newState);
    localStorage.setItem('huni_auth', JSON.stringify({ user, serverUrl }));
  }, []);

  const logout = useCallback(() => {
    setState({ user: null, serverUrl: '', isConnected: false });
    localStorage.removeItem('huni_auth');
  }, []);

  const checkExistingUser = useCallback(async (serverUrl: string) => {
    setServerUrl(serverUrl);
    try {
      const saved = localStorage.getItem('huni_auth');
      if (!saved) return null;
      const parsed = JSON.parse(saved);
      const userId = parsed?.user?.id;
      if (!Number.isInteger(userId) || userId <= 0) return null;
      const res = await api.get(`/auth/check?userId=${userId}`);
      return res.data.user;
    } catch {
      return null;
    }
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, checkExistingUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
