/**
 * app.js — Фабрика Express-приложения для Dashboard API.
 *
 * Используется как в production (server.js), так и в тестах.
 * Каждый вызов createApp() создаёт независимое Express-приложение
 * со своей БД и JWT-секретом.
 */

const express = require('express');
const cors = require('cors');
const { initDB } = require('./db');
const { authMiddleware } = require('./middleware');
const authRoutes = require('./routes/auth.routes');
const postRoutes = require('./routes/post.routes');

/**
 * Создать Express-приложение с указанной БД и JWT-секретом.
 *
 * @param {object} config
 * @param {string} config.dbPath          — путь к SQLite файлу
 * @param {string} config.jwtSecret       — секрет для JWT
 * @param {boolean} [config.seedAdmin]    — сидировать admin/admin (default: true)
 * @returns {{ app: express.Application, db: object }}
 */
function createApp({ dbPath, jwtSecret, seedAdmin = true }) {
  // Инициализация БД
  const db = initDB(dbPath, { seedAdmin });

  // Express
  const app = express();
  app.use(cors());
  app.use(express.json());

  // Dependency Injection через app.locals
  app.locals.db = db;
  app.locals.jwtSecret = jwtSecret;

  // Routes
  app.use('/api/auth', authRoutes);
  app.use('/api/posts', authMiddleware, postRoutes);

  // Health
  app.get('/api/health', (_req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  return { app, db };
}

module.exports = { createApp };
