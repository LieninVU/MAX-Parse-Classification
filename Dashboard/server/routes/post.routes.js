/**
 * routes/post.routes.js — Эндпоинты работы с постами (защищённые).
 * Подключается с middleware authMiddleware в server.js.
 */

const express = require('express');
const { getPosts, deletePost, getCategories } = require('../db');

const router = express.Router();

// ---------------------------------------------------------------------------
// GET /api/posts?category=...&urgency=...&status=...
// ---------------------------------------------------------------------------
router.get('/', (req, res) => {
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
// DELETE /api/posts/:id
// ---------------------------------------------------------------------------
router.delete('/:id', (req, res) => {
  try {
    const { id } = req.params;
    const deleted = deletePost(Number(id));

    if (!deleted) {
      return res.status(404).json({ error: 'Пост не найден' });
    }

    res.json({ message: 'Пост удалён', id: Number(id) });
  } catch (err) {
    console.error('Ошибка удаления поста:', err);
    res.status(500).json({ error: 'Ошибка удаления записи' });
  }
});

// ---------------------------------------------------------------------------
// GET /api/categories
// ---------------------------------------------------------------------------
router.get('/categories', (req, res) => {
  try {
    const categories = getCategories();
    res.json(categories);
  } catch (err) {
    console.error('Ошибка получения категорий:', err);
    res.status(500).json({ error: 'Ошибка чтения базы данных' });
  }
});

module.exports = router;
