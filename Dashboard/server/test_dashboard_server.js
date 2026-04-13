/**
 * test_dashboard_server.js — Интеграционные тесты Dashboard API.
 *
 * Архитектура:
 *   • Каждый тест создаёт своё Express-приложение через createApp()
 *   • Уникальная SQLite БД во временной директории
 *   • supertest для HTTP-запросов (без реального сервера)
 *   • cleanup БД после каждого теста
 *
 * Запуск: node test_dashboard_server.js
 */

const path = require('path');
const os = require('os');
const fs = require('fs');
const crypto = require('crypto');
const jwt = require('jsonwebtoken');
const request = require('supertest');
const { createApp } = require('./app');

// ============================================================================
// TEST FRAMEWORK
// ============================================================================

let passed = 0;
let failed = 0;
const results = [];

async function test(name, fn) {
  try {
    await fn();
    passed++;
    results.push({ name, status: 'OK' });
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed++;
    results.push({ name, status: 'FAIL', error: err.message });
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${err.message}`);
  }
}

function assertEqual(actual, expected, msg = '') {
  if (actual !== expected) {
    throw new Error(`${msg} Expected "${expected}", got "${actual}"`);
  }
}

function assertTrue(value, msg = '') {
  if (!value) {
    throw new Error(`${msg} Expected truthy value`);
  }
}

function assertContains(str, substring, msg = '') {
  if (!String(str).includes(substring)) {
    throw new Error(`${msg} Expected to contain "${substring}"`);
  }
}

// ============================================================================
// HELPER: создать изолированное приложение + cleanup
// ============================================================================

function createTestApp() {
  const dbPath = path.join(
    os.tmpdir(),
    `test_dash_${crypto.randomBytes(4).toString('hex')}.db`
  );
  const jwtSecret = 'test-jwt-secret-key-for-testing-only';

  const { app, db } = createApp({
    dbPath,
    jwtSecret,
    seedAdmin: true,
  });

  return { app, db, dbPath, jwtSecret };
}

function cleanupTestApp({ db, dbPath }) {
  db.close();
  try { fs.unlinkSync(dbPath); } catch (e) {}
  // Удаляем WAL/SHM файлы
  try { fs.unlinkSync(dbPath + '-wal'); } catch (e) {}
  try { fs.unlinkSync(dbPath + '-shm'); } catch (e) {}
}

// ============================================================================
// HELPER: создать JWT токен
// ============================================================================

function makeToken(jwtSecret, payload = {}) {
  return jwt.sign(
    { id: 1, username: 'admin', role: 'admin', ...payload },
    jwtSecret,
    { expiresIn: payload.expiresIn || '1h' }
  );
}

// ============================================================================
// ТЕСТЫ
// ============================================================================

async function runAllTests() {
  console.log('\nТЕСТИРОВАНИЕ DASHBOARD SERVER (Express + SQLite + JWT)\n');

  // -------------------------------------------------------------------------
  // 1. Health Check
  // -------------------------------------------------------------------------
  console.log('1. Health Check');

  await test('GET /api/health возвращает 200', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app).get('/api/health');
      assertEqual(res.status, 200);
      assertEqual(res.body.status, 'ok');
      assertTrue(res.body.timestamp);
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 2. Регистрация
  // -------------------------------------------------------------------------
  console.log('\n2. Регистрация пользователей');

  await test('POST /api/auth/register — успешная регистрация', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'testuser', password: 'testpass' });
      assertEqual(res.status, 201);
      assertEqual(res.body.message, 'Пользователь создан');
      assertEqual(res.body.user.username, 'testuser');
      assertEqual(res.body.user.role, 'admin');
    } finally { cleanupTestApp(ctx); }
  });

  await test('POST /api/auth/register — логин < 3 символов', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'ab', password: 'testpass' });
      assertEqual(res.status, 400);
    } finally { cleanupTestApp(ctx); }
  });

  await test('POST /api/auth/register — пароль < 3 символов', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'testuser', password: 'ab' });
      assertEqual(res.status, 400);
    } finally { cleanupTestApp(ctx); }
  });

  await test('POST /api/auth/register — дубликат username', async () => {
    const ctx = createTestApp();
    try {
      await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'dup', password: 'pass123' });
      const res = await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'dup', password: 'pass456' });
      assertEqual(res.status, 409);
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 3. Авторизация
  // -------------------------------------------------------------------------
  console.log('\n3. Авторизация');

  await test('POST /api/auth/login — успешный вход', async () => {
    const ctx = createTestApp();
    try {
      await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'user1', password: 'pass123' });
      const res = await request(ctx.app)
        .post('/api/auth/login')
        .send({ username: 'user1', password: 'pass123' });
      assertEqual(res.status, 200);
      assertEqual(res.body.message, 'Вход выполнен');
      assertTrue(res.body.token);
    } finally { cleanupTestApp(ctx); }
  });

  await test('POST /api/auth/login — неверный пароль', async () => {
    const ctx = createTestApp();
    try {
      await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'user1', password: 'pass123' });
      const res = await request(ctx.app)
        .post('/api/auth/login')
        .send({ username: 'user1', password: 'wrong' });
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  await test('POST /api/auth/login — несуществующий пользователь', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .post('/api/auth/login')
        .send({ username: 'nouser', password: 'pass123' });
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 4. Seed admin
  // -------------------------------------------------------------------------
  console.log('\n4. Seed admin');

  await test('admin/admin создан при первом запуске', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .post('/api/auth/login')
        .send({ username: 'admin', password: 'admin' });
      assertEqual(res.status, 200);
      assertEqual(res.body.user.role, 'admin');
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 5. JWT Middleware (защита маршрутов)
  // -------------------------------------------------------------------------
  console.log('\n5. JWT Middleware (защита маршрутов)');

  await test('GET /api/posts без токена → 401', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app).get('/api/posts');
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  await test('DELETE /api/posts/1 без токена → 401', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app).delete('/api/posts/1');
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  await test('GET /api/posts с невалидным токеном → 403', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', 'Bearer invalidtoken');
      assertEqual(res.status, 403);
    } finally { cleanupTestApp(ctx); }
  });

  await test('GET /api/posts с валидным JWT → 200', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 200);
      assertTrue(Array.isArray(res.body));
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 6. Posts CRUD (работа с инцидентами)
  // -------------------------------------------------------------------------
  console.log('\n6. Posts CRUD (работа с инцидентами)');

  await test('GET /api/posts — пустой список (с авторизацией)', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 200);
      assertTrue(Array.isArray(res.body));
      assertEqual(res.body.length, 0);
    } finally { cleanupTestApp(ctx); }
  });

  await test('DELETE /api/posts/99999 — удаление несуществующего поста', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .delete('/api/posts/99999')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 404);
    } finally { cleanupTestApp(ctx); }
  });

  await test('GET /api/posts?urgency=high — фильтрация по срочности', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .get('/api/posts?urgency=high')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 200);
      assertTrue(Array.isArray(res.body));
    } finally { cleanupTestApp(ctx); }
  });

  await test('GET /api/posts?category=ЖКХ — фильтрация по категории', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .get('/api/posts?category=ЖКХ')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 200);
      assertTrue(Array.isArray(res.body));
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 7. Категории
  // -------------------------------------------------------------------------
  console.log('\n7. Категории');

  await test('GET /api/posts/categories — пустой список', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .get('/api/posts/categories')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 200);
      assertTrue(Array.isArray(res.body));
      assertEqual(res.body.length, 0);
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 8. JWT Edge Cases
  // -------------------------------------------------------------------------
  console.log('\n8. JWT Edge Cases');

  await test('JWT expired token → 401', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret, { expiresIn: '0s' });
      // Задержка чтобы токен истёк
      await new Promise((r) => setTimeout(r, 200));
      const res = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  await test('JWT без Bearer prefix → 401', async () => {
    const ctx = createTestApp();
    try {
      const token = makeToken(ctx.jwtSecret);
      const res = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', token);
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  await test('JWT пустой Authorization header → 401', async () => {
    const ctx = createTestApp();
    try {
      const res = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', '');
      assertEqual(res.status, 401);
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // 9. Полный сценарий (end-to-end)
  // -------------------------------------------------------------------------
  console.log('\n9. Полный сценарий (end-to-end)');

  await test('register → login → GET /api/posts (200)', async () => {
    const ctx = createTestApp();
    try {
      const regRes = await request(ctx.app)
        .post('/api/auth/register')
        .send({ username: 'e2euser', password: 'e2epass' });
      assertEqual(regRes.status, 201);

      const loginRes = await request(ctx.app)
        .post('/api/auth/login')
        .send({ username: 'e2euser', password: 'e2epass' });
      assertEqual(loginRes.status, 200);
      const token = loginRes.body.token;

      const postsRes = await request(ctx.app)
        .get('/api/posts')
        .set('Authorization', `Bearer ${token}`);
      assertEqual(postsRes.status, 200);
    } finally { cleanupTestApp(ctx); }
  });

  // -------------------------------------------------------------------------
  // SUMMARY
  // -------------------------------------------------------------------------
  console.log('\n' + '='.repeat(60));
  console.log(`РЕЗУЛЬТАТЫ: ${passed} пройдено, ${failed} провалено`);
  console.log('='.repeat(60));

  results.forEach((r) => {
    const icon = r.status === 'OK' ? '✓' : '✗';
    console.log(`  ${icon} ${r.name} — ${r.status}`);
    if (r.error) console.log(`    ${r.error}`);
  });

  if (failed === 0) {
    console.log('\n✅ Все тесты пройдены успешно!');
  }

  process.exitCode = failed > 0 ? 1 : 0;
}

runAllTests().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});
