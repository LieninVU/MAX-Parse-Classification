/**
 * middleware.js — JWT-верификация для защищённых эндпоинтов.
 */

const jwt = require('jsonwebtoken');

/**
 * Express-middleware: проверяет заголовок Authorization: Bearer <token>.
 * При успехе — кладёт decoded payload в req.user.
 * При ошибке — возвращает 401.
 */
function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization;

  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Токен не предоставлен' });
  }

  const token = authHeader.split(' ')[1];
  const secret = process.env.JWT_SECRET;

  if (!secret) {
    console.error('❌ JWT_SECRET не настроен в .env');
    return res.status(500).json({ error: 'Сервер не настроен' });
  }

  try {
    const decoded = jwt.verify(token, secret);
    req.user = decoded; // { id, username, role }
    next();
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      return res.status(401).json({ error: 'Токен истёк. Войдите заново.' });
    }
    return res.status(403).json({ error: 'Невалидный токен' });
  }
}

module.exports = { authMiddleware };
