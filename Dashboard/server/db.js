/**
 * db.js — Инициализация SQLite, создание таблиц, сидирование пользователя admin/admin.
 *
 * Ожидает, что переменные окружения (DB_PATH) уже загружены
 * через dotenv.config() в server.js.
 */

const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const DB_PATH =
  process.env.DB_PATH || path.join(__dirname, '../../AI/analytics.db');

// Убеждаемся, что директория БД существует
const dbDir = path.dirname(DB_PATH);
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Инициализация подключения
// ---------------------------------------------------------------------------
const db = new Database(DB_PATH);

// WAL-режим для конкурентного доступа (FastAPI + Express работают с одной БД)
db.pragma('journal_mode = WAL');

// ---------------------------------------------------------------------------
// SQL: таблица пользователей
// ---------------------------------------------------------------------------
const SQL_CREATE_USERS = `
  CREATE TABLE IF NOT EXISTS dashboard_users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT    NOT NULL UNIQUE,
    password  TEXT    NOT NULL,
    role      TEXT    NOT NULL DEFAULT 'admin',
    created_at TEXT   NOT NULL DEFAULT (datetime('now'))
  )
`;

// ---------------------------------------------------------------------------
// SQL: таблица инцидентов (совместимость с FastAPI-analytics_server.py)
// ---------------------------------------------------------------------------
const SQL_CREATE_ACTIONABLE = `
  CREATE TABLE IF NOT EXISTS actionable_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL,
    channel_id          INTEGER NOT NULL,
    channel_name        TEXT    NOT NULL,
    text                TEXT,
    link                TEXT,
    timestamp           INTEGER NOT NULL,
    date                TEXT    NOT NULL,
    requires_response   INTEGER NOT NULL,
    category            TEXT    NOT NULL,
    urgency             TEXT    NOT NULL,
    reason              TEXT    NOT NULL,
    draft_reply_thesis  TEXT,
    ai_raw_response     TEXT,
    analyzed_at         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'new',
    UNIQUE(message_id, channel_id)
  )
`;

const SQL_INDEXES = [
  'CREATE INDEX IF NOT EXISTS idx_actionable_urgency ON actionable_posts(urgency)',
  'CREATE INDEX IF NOT EXISTS idx_actionable_status  ON actionable_posts(status)',
  'CREATE INDEX IF NOT EXISTS idx_actionable_date    ON actionable_posts(date)',
  'CREATE INDEX IF NOT EXISTS idx_actionable_category ON actionable_posts(category)',
];

// ---------------------------------------------------------------------------
// Prepared-стейтменты (кешируем — better-sqlite3 рекомендует)
// ---------------------------------------------------------------------------
const stmt = {
  countUsers: db.prepare('SELECT COUNT(*) as cnt FROM dashboard_users'),
  insertUser: db.prepare(
    'INSERT INTO dashboard_users (username, password, role) VALUES (?, ?, ?)'
  ),
  findUser: db.prepare(
    'SELECT * FROM dashboard_users WHERE username = ?'
  ),
  createUser: db.prepare(
    'INSERT INTO dashboard_users (username, password) VALUES (?, ?)'
  ),
  deletePost: db.prepare(
    'DELETE FROM actionable_posts WHERE id = ?'
  ),
  getCategories: db.prepare(
    'SELECT DISTINCT category FROM actionable_posts ORDER BY category'
  ),
};

// ---------------------------------------------------------------------------
// Сидирование
// ---------------------------------------------------------------------------
function seedDefaultUser() {
  const { cnt } = stmt.countUsers.get();

  if (cnt === 0) {
    const bcrypt = require('bcryptjs');
    const hashedPassword = bcrypt.hashSync('admin', 10);
    stmt.insertUser.run('admin', hashedPassword, 'admin');
    console.log('✅ Создан пользователь по умолчанию: admin / admin');
  }
}

// ---------------------------------------------------------------------------
// Инициализация
// ---------------------------------------------------------------------------
function initDatabase() {
  db.exec(SQL_CREATE_USERS);
  db.exec(SQL_CREATE_ACTIONABLE);
  SQL_INDEXES.forEach((sql) => db.exec(sql));
  seedDefaultUser();
  console.log(`📁 База данных: ${DB_PATH}`);
}

initDatabase();

// ---------------------------------------------------------------------------
// Публичный API модуля
// ---------------------------------------------------------------------------

/**
 * Получить посты с фильтрацией.
 * @param {{ category?: string, urgency?: string, status?: string }} filters
 */
function getPosts(filters = {}) {
  let query = 'SELECT * FROM actionable_posts WHERE 1=1';
  const params = [];

  if (filters.category) {
    query += ' AND category = ?';
    params.push(filters.category);
  }
  if (filters.urgency) {
    query += ' AND urgency = ?';
    params.push(filters.urgency);
  }
  if (filters.status) {
    query += ' AND status = ?';
    params.push(filters.status);
  }

  query += `
    ORDER BY
      CASE urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
      date DESC
    LIMIT 200
  `;

  return db.prepare(query).all(...params);
}

/**
 * Удалить пост по ID.
 * @returns {boolean} true если строка была удалена
 */
function deletePost(id) {
  const { changes } = stmt.deletePost.run(id);
  return changes > 0;
}

/**
 * Получить уникальные категории.
 * @returns {string[]}
 */
function getCategories() {
  return stmt.getCategories.all().map((row) => row.category);
}

/**
 * Найти пользователя по username.
 * @returns {{ id: number, username: string, password: string, role: string } | undefined}
 */
function findUserByUsername(username) {
  return stmt.findUser.get(username);
}

/**
 * Создать пользователя.
 * @returns {{ lastInsertRowid: number }}
 */
function createUser(username, hashedPassword) {
  return stmt.createUser.run(username, hashedPassword);
}

module.exports = {
  getPosts,
  deletePost,
  getCategories,
  findUserByUsername,
  createUser,
};
