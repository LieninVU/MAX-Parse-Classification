/**
 * db.js — Инициализация SQLite, создание таблиц, сидирование пользователя admin/admin.
 * Использует better-sqlite3 (синхронный, с промис-обёрткой для удобства).
 */

const Database = require('better-sqlite3');
const bcrypt = require('bcryptjs');
const path = require('path');
const fs = require('fs');

// ---------------------------------------------------------------------------
// Загрузка .env вручную (без зависимости dotenv в этом файле для простоты)
// Лучше использовать dotenv в server.js, а сюда передавать готовый конфиг.
// Но для автономности — читаем .env здесь.
// ---------------------------------------------------------------------------

function loadEnv() {
  const envPath = path.join(__dirname, '.env');
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf-8');
    content.split('\n').forEach((line) => {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#')) {
        const [key, ...rest] = trimmed.split('=');
        process.env[key.trim()] = rest.join('=').trim();
      }
    });
  }
}

loadEnv();

const DB_PATH = process.env.DB_PATH || path.join(__dirname, '../../AI/analytics.db');

// Убеждаемся, что директория БД существует
const dbDir = path.dirname(DB_PATH);
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Инициализация подключения
// ---------------------------------------------------------------------------
const db = new Database(DB_PATH);

// Включаем WAL-режим для лучшей конкурентности (FastAPI + Express работают с одной БД)
db.pragma('journal_mode = WAL');

// ---------------------------------------------------------------------------
// SQL: таблица пользователей (новая)
// ---------------------------------------------------------------------------
const SQL_CREATE_USERS = `
  CREATE TABLE IF NOT EXISTS dashboard_users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT    NOT NULL UNIQUE,
    password  TEXT    NOT NULL,          -- bcrypt-хеш
    role      TEXT    NOT NULL DEFAULT 'admin',
    created_at TEXT   NOT NULL DEFAULT (datetime('now'))
  )
`;

// ---------------------------------------------------------------------------
// SQL: убедимся, что actionable_posts существует (совместимость с FastAPI)
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
// Сидирование: создаём admin/admin, если пользователей нет
// ---------------------------------------------------------------------------
function seedDefaultUser() {
  const count = db.prepare('SELECT COUNT(*) as cnt FROM dashboard_users').get();

  if (count.cnt === 0) {
    const hashedPassword = bcrypt.hashSync('admin', 10);
    const stmt = db.prepare(
      'INSERT INTO dashboard_users (username, password, role) VALUES (?, ?, ?)'
    );
    stmt.run('admin', hashedPassword, 'admin');
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
// Экспорт объекта db и хелперов
// ---------------------------------------------------------------------------
module.exports = {
  db,

  /** Получить все посты с фильтрацией */
  getPosts(filters = {}) {
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

    // Сортировка: high → medium → low, затем по дате
    query += `
      ORDER BY
        CASE urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
        date DESC
      LIMIT 200
    `;

    return db.prepare(query).all(...params);
  },

  /** Удалить пост по ID */
  deletePost(id) {
    const result = db.prepare('DELETE FROM actionable_posts WHERE id = ?').run(id);
    return result.changes > 0;
  },

  /** Получить уникальные категории */
  getCategories() {
    return db
      .prepare('SELECT DISTINCT category FROM actionable_posts ORDER BY category')
      .all()
      .map((r) => r.category);
  },

  /** Проверить пользователя по username */
  findUserByUsername(username) {
    return db
      .prepare('SELECT * FROM dashboard_users WHERE username = ?')
      .get(username);
  },

  /** Создать нового пользователя */
  createUser(username, hashedPassword) {
    return db
      .prepare('INSERT INTO dashboard_users (username, password) VALUES (?, ?)')
      .run(username, hashedPassword);
  },
};
