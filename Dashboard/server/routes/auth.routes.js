/**
 * routes/auth.routes.js — Эндпоинты регистрации и авторизации.
 *
 * Использует БД и JWT-секрет из req.app.locals (Dependency Injection).
 */

const express = require('express');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');

const router = express.Router();

// ---------------------------------------------------------------------------
// POST /api/auth/register
// ---------------------------------------------------------------------------
router.post('/register', (req, res) => {
  const { username, password } = req.body;
  const { findUserByUsername, createUser } = req.app.locals.db;

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

  const existing = findUserByUsername(username);
  if (existing) {
    return res.status(409).json({
      error: 'Пользователь с таким логином уже существует',
    });
  }

  try {
    const hashedPassword = bcrypt.hashSync(password, 10);
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
// POST /api/auth/login
// ---------------------------------------------------------------------------
router.post('/login', (req, res) => {
  const { username, password } = req.body;
  const { findUserByUsername } = req.app.locals.db;
  const jwtSecret = req.app.locals.jwtSecret;

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

  const token = jwt.sign(
    { id: user.id, username: user.username, role: user.role },
    jwtSecret,
    { expiresIn: '24h' }
  );

  res.json({
    message: 'Вход выполнен',
    token,
    user: { id: user.id, username: user.username, role: user.role },
  });
});

module.exports = router;
