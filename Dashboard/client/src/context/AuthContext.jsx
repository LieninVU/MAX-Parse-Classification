/**
 * AuthContext.jsx — React Context для управления авторизацией.
 * Хранит токен и данные пользователя в localStorage + state.
 *
 * Использует api.js (с interceptors) вместо мутации axios.defaults.
 */

import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // При монтировании проверяем сохранённый токен
  useEffect(() => {
    const savedUser = localStorage.getItem('dashboard_user');
    const savedToken = localStorage.getItem('dashboard_token');

    if (savedUser && savedToken) {
      setUser(JSON.parse(savedUser));
    }
    setLoading(false);
  }, []);

  /** Войти: сохранить токен и пользователя */
  const login = (token, userData) => {
    localStorage.setItem('dashboard_token', token);
    localStorage.setItem('dashboard_user', JSON.stringify(userData));
    setUser(userData);
  };

  /** Выйти: очистить всё */
  const logout = () => {
    localStorage.removeItem('dashboard_token');
    localStorage.removeItem('dashboard_user');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

/** Хук для использования контекста авторизации */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

export default AuthContext;
