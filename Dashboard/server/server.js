/**
 * server.js — Express-сервер для Admin Dashboard.
 *
 * Эндпоинты:
 *   POST /api/auth/register  — регистрация
 *   POST /api/auth/login     — логин → JWT
 *   GET  /api/posts          — список постов (фильтрация через query)
 *   DELETE /api/posts/:id    — удаление поста
 *   GET  /api/categories     — список уникальных категорий
 */

require('dotenv').config(); // Загруем .env ДО всего остального

const express = require('express');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const { db, getPosts, deletePost, getCategories, findUserByUsername, createUser } = require('./db');
const { authMiddleware } = require('./middleware');

const app = express();
const PORT = process.env.PORT || 5000;

// ---------------------------------------------------------------------------
// Middleware
// ---------------------------------------------------------------------------
app.use(cors()); // Разрешаем запросы с фронтенда (Vite dev server на другом порту)
app.use(express.json());

// ---------------------------------------------------------------------------
// AUTH — /api/auth/register
// ---------------------------------------------------------------------------
app.post('/api/auth/register', (req, res) => {
  const { username, password } = req.body;

  // Валидация
  if (!username || !password) {
    return res.status(400).json({ error: 'Логин и пароль обязательны' });
  }
  if (typeof username !== 'string' || username.length < 3) {
    return res.status(400).json({ error: 'Логин минимум 3 символа' });
  }
  if (typeof password !== 'string' || password.length < 3) {
    return res.status(400).json({ error: 'Пароль минимум 3 символа' });
  }

  // Проверяем, не занят ли username
  const existing = findUserByUsername(username);
  if (existing) {
    return res.status(409).json({ error: 'Пользователь с таким логином уже существует' });
  }

  // Хэшируем и сохраняем
  const hashedPassword = bcrypt.hashSync(password, 10);
  try {
    const result = createUser(username, hashedPassword);
    return res.status(201).json({
      message: 'Пользователь создан',
      user: { id: result.lastInsertRowid, username, role: 'admin' },
    });
  } catch (err) {
    console.error('Ошибка регистрации:', err);
    return res.status(500).json({ error: 'Ошибка сервера при регистрации' });
  }
});

// ---------------------------------------------------------------------------
// AUTH — /api/auth/login
// ---------------------------------------------------------------------------
app.post('/api/auth/login', (req, res) => {
  const { username, password } = req.body;

  if (!username || !password) {
    return res.status(400).json({ error: 'Логин и пароль обязательны' });
  }

  const user = findUserByUsername(username);
  if (!user) {
    return res.status(401).json({ error: 'Неверный логин или пароль' });
  }

  const isValid = bcrypt.compareSync(password, user.password);
  if (!isValid) {
    return res.status(401).json({ error: 'Неверный логин или пароль' });
  }

  // Генерируем JWT
  const secret = process.env.JWT_SECRET;
  if (!secret) {
    console.error('❌ JWT_SECRET не настроен');
    return res.status(500).json({ error: 'Сервер не настроен' });
  }

  const token = jwt.sign(
    { id: user.id, username: user.username, role: user.role },
    secret,
    { expiresIn: '24h' }
  );

  res.json({
    message: 'Вход выполнен',
    token,
    user: { id: user.id, username: user.username, role: user.role },
  });
});

// ---------------------------------------------------------------------------
// POSTS — GET /api/posts?category=...&urgency=...&status=...
// ---------------------------------------------------------------------------
app.get('/api/posts', authMiddleware, (req, res) => {
  try {
    const { category, urgency, status } = req.query;
    const posts = getPosts({ category, urgency, status });
    res.json(posts);
  } catch (err) {
    console.error('Ошибка получения постов:', err);
    res.status(500).json({ error: 'Ошибка чтения базы данных' });
  }
});

// ---------------------------------------------------------------------------
// POSTS — DELETE /api/posts/:id
// ---------------------------------------------------------------------------
app.delete('/api/posts/:id', authMiddleware, (req, res) => {
  const { id } = req.params;
  const deleted = deletePost(id);

  if (!deleted) {
    return res.status(404).json({ error: 'Пост не найден' });
  }

  res.json({ message: 'Пост удалён', id });
});

// ---------------------------------------------------------------------------
// CATEGORIES — GET /api/categories
// ---------------------------------------------------------------------------
app.get('/api/categories', authMiddleware, (req, res) => {
  try {
    const categories = getCategories();
    res.json(categories);
  } catch (err) {
    console.error('Ошибка получения категорий:', err);
    res.status(500).json({ error: 'Ошибка чтения базы данных' });
  }
});

// ---------------------------------------------------------------------------
// HEALTH
// ---------------------------------------------------------------------------
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ---------------------------------------------------------------------------
// Запуск
// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`🚀 Dashboard API запущен → http://localhost:${PORT}`);
});
