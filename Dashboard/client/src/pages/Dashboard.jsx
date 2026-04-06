/**
 * Dashboard.jsx — Главная страница администратора.
 * Таблица инцидентов с фильтрацией (категория, срочность) и удалением.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/api';
import { useAuth } from '../context/AuthContext';

// ---------------------------------------------------------------------------
// Константы (на уровне модуля — не аллоцируются при каждом рендере)
// ---------------------------------------------------------------------------
const URGENCY_META = {
  high:   { label: 'Высокая',  color: 'bg-red-100 text-red-800' },
  medium: { label: 'Средняя',  color: 'bg-yellow-100 text-yellow-800' },
  low:    { label: 'Низкая',   color: 'bg-green-100 text-green-800' },
};

const STATUS_COLORS = {
  new:         'bg-blue-100 text-blue-800',
  in_progress: 'bg-yellow-100 text-yellow-800',
  resolved:    'bg-green-100 text-green-800',
  ignored:     'bg-gray-100 text-gray-500',
};

const DEFAULT_URGENCY = { label: '—', color: 'bg-gray-100 text-gray-800' };
const DEFAULT_STATUS  = 'bg-gray-100 text-gray-800';

// ---------------------------------------------------------------------------
// Хелперы
// ---------------------------------------------------------------------------
function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

// ---------------------------------------------------------------------------
// Компонент
// ---------------------------------------------------------------------------
export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [posts, setPosts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [filterCategory, setFilterCategory] = useState('');
  const [filterUrgency, setFilterUrgency] = useState('');

  // -----------------------------------------------------------------------
  // Загрузка категорий
  // -----------------------------------------------------------------------
  const fetchCategories = useCallback(async () => {
    try {
      const res = await api.get('/posts/categories');
      setCategories(res.data);
    } catch {
      // Не критично — фильтр просто будет пустым
    }
  }, []);

  // -----------------------------------------------------------------------
  // Загрузка постов
  // -----------------------------------------------------------------------
  const fetchPosts = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = {};
      if (filterCategory) params.category = filterCategory;
      if (filterUrgency) params.urgency = filterUrgency;

      const res = await api.get('/posts', { params });
      setPosts(res.data);
    } catch (err) {
      // 401 уже обработан interceptor в api.js
      if (err.response?.status !== 401 && err.response?.status !== 403) {
        setError('Ошибка загрузки данных');
      }
    } finally {
      setLoading(false);
    }
  }, [filterCategory, filterUrgency]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  useEffect(() => {
    fetchPosts();
  }, [fetchPosts]);

  // -----------------------------------------------------------------------
  // Удаление поста
  // -----------------------------------------------------------------------
  const handleDelete = async (id) => {
    if (!window.confirm('Удалить этот инцидент?')) return;

    try {
      await api.delete(`/posts/${id}`);
      setPosts((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      alert('Ошибка удаления: ' + (err.response?.data?.error || err.message));
    }
  };

  // -----------------------------------------------------------------------
  // Выход
  // -----------------------------------------------------------------------
  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  // -----------------------------------------------------------------------
  // Reset фильтров
  // -----------------------------------------------------------------------
  const resetFilters = useCallback(() => {
    setFilterCategory('');
    setFilterUrgency('');
  }, []);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <div className="min-h-screen bg-slate-50">
      {/* ===== HEADER ===== */}
      <header className="bg-white shadow-sm border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">🏙️ Инциденты</h1>
            <p className="text-sm text-slate-500">
              Пользователь:{' '}
              <span className="font-medium text-slate-700">{user?.username}</span>
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="px-4 py-2 text-sm font-medium text-red-600 border border-red-300 rounded-lg hover:bg-red-50 transition"
          >
            Выйти
          </button>
        </div>
      </header>

      {/* ===== MAIN CONTENT ===== */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Панель фильтров */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 mb-6">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Категория
              </label>
              <select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-white"
              >
                <option value="">Все категории</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>

            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Срочность
              </label>
              <select
                value={filterUrgency}
                onChange={(e) => setFilterUrgency(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-white"
              >
                <option value="">Любая</option>
                <option value="high">🔴 Высокая</option>
                <option value="medium">🟡 Средняя</option>
                <option value="low">🟢 Низкая</option>
              </select>
            </div>

            <button
              onClick={resetFilters}
              className="px-4 py-2 text-sm font-medium text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-50 transition"
            >
              Сбросить
            </button>
          </div>
        </div>

        {/* Ошибка */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
            {error}
          </div>
        )}

        {/* Таблица */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          {loading ? (
            <div className="p-12 text-center text-slate-500">Загрузка данных...</div>
          ) : posts.length === 0 ? (
            <div className="p-12 text-center text-slate-500">
              Нет инцидентов по выбранным фильтрам
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 text-slate-600 uppercase text-xs border-b border-slate-200">
                  <tr>
                    <th className="px-4 py-3">ID</th>
                    <th className="px-4 py-3">Канал</th>
                    <th className="px-4 py-3 min-w-[250px]">Текст</th>
                    <th className="px-4 py-3">Категория</th>
                    <th className="px-4 py-3">Срочность</th>
                    <th className="px-4 py-3">Статус</th>
                    <th className="px-4 py-3">Дата</th>
                    <th className="px-4 py-3">Действие</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {posts.map((post) => (
                    <tr key={post.id} className="hover:bg-slate-50 transition">
                      <td className="px-4 py-3 font-mono text-xs text-slate-500">
                        #{post.id}
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-800">
                        {post.channel_name}
                      </td>
                      <td className="px-4 py-3 max-w-xs">
                        <div className="truncate" title={post.text}>
                          {post.text || '—'}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-block px-2 py-1 text-xs font-medium rounded bg-slate-100 text-slate-700">
                          {post.category}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-1 text-xs font-medium rounded ${
                            (URGENCY_META[post.urgency] || DEFAULT_URGENCY).color
                          }`}
                        >
                          {(URGENCY_META[post.urgency] || DEFAULT_URGENCY).label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block px-2 py-1 text-xs font-medium rounded ${
                            STATUS_COLORS[post.status] || DEFAULT_STATUS
                          }`}
                        >
                          {post.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                        {formatDate(post.date)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleDelete(post.id)}
                          className="px-3 py-1 text-xs font-medium text-white bg-red-500 hover:bg-red-600 rounded transition"
                        >
                          Удалить
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Счётчик */}
        {!loading && posts.length > 0 && (
          <div className="mt-4 text-sm text-slate-500">
            Показано: {posts.length} инцидент(ов)
          </div>
        )}
      </main>
    </div>
  );
}
