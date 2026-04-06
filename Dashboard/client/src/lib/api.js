/**
 * lib/api.js — Axios-instance с interceptors для Dashboard API.
 *
 * Заменяет глобальную мутацию axios.defaults.
 * Автоматически подставляет токен из localStorage и обрабатывает 401.
 */

import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
});

// ---------------------------------------------------------------------------
// Request interceptor: подставить JWT-токен
// ---------------------------------------------------------------------------
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('dashboard_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------------------------------------------------------------------------
// Response interceptor: при 401 — очистить сессию
// ---------------------------------------------------------------------------
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Токен истёк или невалиден — чистим сессию
      localStorage.removeItem('dashboard_token');
      localStorage.removeItem('dashboard_user');
      // Редирект на логин
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
