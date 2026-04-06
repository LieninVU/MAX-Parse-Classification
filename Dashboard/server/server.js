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

require('dotenv').config();

const express = require('express');
const cors = require('cors');
const { authMiddleware } = require('./middleware');
const authRoutes = require('./routes/auth.routes');
const postRoutes = require('./routes/post.routes');

// ---------------------------------------------------------------------------
// Валидация конфига при старте (fail-fast)
// ---------------------------------------------------------------------------
if (!process.env.JWT_SECRET) {
  console.error('❌ JWT_SECRET не настроен в .env');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Express setup
// ---------------------------------------------------------------------------
const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors());
app.use(express.json());

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------
app.use('/api/auth', authRoutes);
app.use('/api/posts', authMiddleware, postRoutes);

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`🚀 Dashboard API запущен → http://localhost:${PORT}`);
});
