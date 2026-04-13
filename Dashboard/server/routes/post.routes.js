/**
 * routes/post.routes.js — Эндпоинты работы с постами (защищённые).
 *
 * Использует БД из req.app.locals (Dependency Injection).
 */

const express = require('express');

const router = express.Router();

// ---------------------------------------------------------------------------
// GET /api/posts?category=...&urgency=...&status=...
// ---------------------------------------------------------------------------
router.get('/', (req, res) => {
  try {
    const { category, urgency, status } = req.query;
    const { getPosts } = req.app.locals.db;
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
    const { deletePost } = req.app.locals.db;
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
    const { getCategories } = req.app.locals.db;
    const categories = getCategories();
    res.json(categories);
  } catch (err) {
    console.error('Ошибка получения категорий:', err);
    res.status(500).json({ error: 'Ошибка чтения базы данных' });
  }
});

module.exports = router;
