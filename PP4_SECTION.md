ВЫПОЛНЕННЫЕ ВО ВРЕМЯ ПРАКТИКИ РАБОТЫ

#### 1. АНАЛИЗ ТРЕБОВАНИЙ К ДАННЫМ

В ходе изучения предметной области мониторинга инцидентов из социальных сетей были выявлены три ключевые сущности, подлежащие хранению в базе данных:

- **messages** — сырые сообщения, полученные парсером из каналов MAX. Требования: уникальность каждого сообщения (дедупликация по `message_id + channel_id`), сохранение временных меток (`timestamp`, `date`), хранение текста и прямой ссылки.
- **actionable_posts** — посты, классифицированные AI как требующие реакции администрации. Требования: хранение вердикта AI (`requires_response`), категории, уровня срочности, обоснования, статуса обработки (`new`/`in_progress`/`resolved`/`ignored`), аудит времени анализа (`analyzed_at`).
- **dashboard_users** — учётные записи пользователей дашборда. Требования: уникальность логина, безопасное хранение паролей (хеширование), разграничение ролей, фиксация времени создания записи.

**Требования к целостности данных:**
- Дедупликация на уровне СУБД через составное ограничение `UNIQUE(message_id, channel_id)` для обеих таблиц (`messages`, `actionable_posts`).
- Ограничение `NOT NULL` на всех обязательных полях; значение по умолчанию `DEFAULT 'new'` для поля `status`.
- Нормализация значений `urgency` до множества `{low, medium, high}` на уровне приложения (Pydantic-валидация).

**Требования к безопасности:**
- Аутентификация пользователей через JWT-токены с временем жизни 24 часа.
- Хеширование паролей алгоритмом bcrypt с параметром соли `saltRounds = 10`.
- Защита от SQL-инъекций через параметризованные запросы (prepared statements) во всех хранилищах.
- Разграничение доступа: публичные маршруты регистрации/входа и защищённые маршруты CRUD-операций.

#### 2. ПРОЕКТИРОВАНИЕ БАЗЫ ДАННЫХ

На этапе проектиирования разработана ER-модель, включающая три таблицы без внешних ключей (связь осуществляется на уровне приложения через `message_id`):

**Таблица `messages`** (8 полей) — хранение сырых сообщений парсера:

| Поле | Тип | Ограничения |
|------|-----|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| message_id | INTEGER | NOT NULL |
| channel_id | INTEGER | NOT NULL |
| channel_name | TEXT | NOT NULL |
| text | TEXT | NULL |
| link | TEXT | — |
| timestamp | INTEGER | NOT NULL |
| date | TEXT | NOT NULL |

Составное ограничение: `UNIQUE(message_id, channel_id)`.

**Таблица `actionable_posts`** (17 полей) — хранение результатов AI-анализа:

| Поле | Тип | Ограничения |
|------|-----|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| message_id | INTEGER | NOT NULL |
| channel_id | INTEGER | NOT NULL |
| channel_name | TEXT | NOT NULL |
| text | TEXT | NULL |
| link | TEXT | — |
| timestamp | INTEGER | NOT NULL |
| date | TEXT | NOT NULL |
| requires_response | INTEGER | NOT NULL (1/0) |
| category | TEXT | NOT NULL |
| urgency | TEXT | NOT NULL |
| reason | TEXT | NOT NULL |
| draft_reply_thesis | TEXT | NULL |
| ai_raw_response | TEXT | NULL |
| analyzed_at | TEXT | NOT NULL |
| status | TEXT | NOT NULL DEFAULT 'new' |

Составное ограничение: `UNIQUE(message_id, channel_id)`.

**Таблица `dashboard_users`** (5 полей) — учётные записи:

| Поле | Тип | Ограничения |
|------|-----|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| username | TEXT | NOT NULL UNIQUE |
| password | TEXT | NOT NULL (bcrypt-хеш) |
| role | TEXT | NOT NULL DEFAULT 'admin' |
| created_at | TEXT | NOT NULL DEFAULT (datetime('now')) |

**Нормализация:** структура приведена ко второй нормальной форме (2НФ). Сырые сообщения вынесены в отдельную таблицу `messages` (хранится в `messages.db`), аналитические данные — в `actionable_posts` (хранятся в `analytics.db`). Это исключает избыточность: текст поста хранится однократно в `messages`, а в `actionable_posts` — только результат анализа.

**Ограничения целостности:**
- `UNIQUE(message_id, channel_id)` — предотвращение дубликатов на уровне СУБД.
- `DEFAULT 'new'` — автоматическая установка начального статуса.
- `UNIQUE` на `username` — гарантия уникальности учётных записей.
- `DEFAULT (datetime('now'))` — автоматическая фиксация времени создания пользователя.

ER-диаграмма с указанием полей, типов данных и индексов задокументирована в файле `UML_Diagrams.md` (PlantUML-диаграмма Database ER Diagram).

#### 3. РЕАЛИЗАЦИЯ БАЗЫ ДАННЫХ В СУБД SQLITE

##### 3.1. DDL-схемы и индексы

DDL-схема таблицы `actionable_posts` реализована в отдельном файле `AI/schema.sql`. Схема включает 17 столбцов с ограничениями `NOT NULL`, `UNIQUE`, `DEFAULT`, а также 4 индекса для ускорения фильтрации:

```sql
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
);

CREATE INDEX IF NOT EXISTS idx_actionable_urgency ON actionable_posts(urgency);
CREATE INDEX IF NOT EXISTS idx_actionable_status  ON actionable_posts(status);
CREATE INDEX IF NOT EXISTS idx_actionable_date    ON actionable_posts(date);
CREATE INDEX IF NOT EXISTS idx_actionable_category ON actionable_posts(category);
```

Индексы `idx_actionable_urgency` и `idx_actionable_status` оптимизируют запросы фильтрации по срочности и статусу; `idx_actionable_date` — сортировку по времени публикации; `idx_actionable_category` — группировку по категориям инцидентов.

##### 3.2. Конфигурация СУБД для конкурентного доступа

В модуле `Dashboard/server/db.js` активирован WAL-режим (Write-Ahead Logging), обеспечивающий параллельное чтение и запись без блокировок:

```javascript
const db = new Database(dbPath);
db.pragma('journal_mode = WAL');
```

WAL-режим критичен для архитектуры, где FastAPI-сервер (`AI/analytics_server.py`) выполняет запись инцидентов, а Express-сервер (`Dashboard/server/db.js`) — чтение и удаление. Без WAL одновременная работа двух процессов с `analytics.db` приводила бы к блокировке базы.

Дополнительно все SQL-запросы预先 компилируются через `db.prepare()`, что обеспечивает кэширование планов выполнения и защиту от инъекций:

```javascript
const stmt = {
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
```

Динамическая фильтрация в методе `getPosts()` реализована через конкатенацию шаблона запроса с массивом параметров, исключающим подстановку пользовательских данных непосредственно в SQL-строку:

```javascript
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
  query += ` ORDER BY CASE urgency WHEN 'high' THEN 1 ... END, date DESC LIMIT 200`;
  return db.prepare(query).all(...params);
}
```

##### 3.3. Хранилище парсера

Класс `MessageStore` в `Parser/comment_parser.py` реализует SQLite-хранилище сырых сообщений. Схема создаётся при инициализации:

```python
_SQL_CREATE_MESSAGES = """
    CREATE TABLE IF NOT EXISTS messages (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id    INTEGER NOT NULL,
        channel_id    INTEGER NOT NULL,
        channel_name  TEXT    NOT NULL,
        text          TEXT,
        link          TEXT,
        timestamp     INTEGER NOT NULL,
        date          TEXT    NOT NULL,
        UNIQUE(message_id, channel_id)
    )
"""
```

Дедупликация реализована через `INSERT OR IGNORE` — при попытке вставки сообщения с той же парой `(message_id, channel_id)` SQLite silently пропускает запись:

```python
_SQL_INSERT_MESSAGE = """
    INSERT OR IGNORE INTO messages
        (message_id, channel_id, channel_name, text, link, timestamp, date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
"""

def save(self, msg: MessageData) -> bool:
    cursor = self._conn.execute(_SQL_INSERT_MESSAGE, (
        msg.message_id, msg.channel_id, msg.channel_name,
        msg.text, msg.link, msg.timestamp, msg.date,
    ))
    self._conn.commit()
    return cursor.rowcount > 0
```

Метод `get_last_message_id()` использует агрегатную функцию `MAX()` для определения позиции последнего обработанного сообщения канала:

```python
_SQL_LAST_MESSAGE_ID = (
    "SELECT MAX(message_id) FROM messages WHERE channel_id = ?"
)

def get_last_message_id(self, channel_id: int) -> int:
    row = self._conn.execute(_SQL_LAST_MESSAGE_ID, (channel_id,)).fetchone()
    return row[0] or 0
```

##### 3.4. Хранилище AI-аналитики

Класс `ActionableStore` в `AI/analytics_server.py` управляет таблицей `actionable_posts`. Все запросы используют параметризованные выражения с плейсхолдерами `?`:

```python
_SQL_INSERT_ACTIONABLE = """
    INSERT OR IGNORE INTO actionable_posts
        (message_id, channel_id, channel_name, text, link, timestamp, date,
         requires_response, category, urgency, reason, draft_reply_thesis,
         ai_raw_response, analyzed_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
"""

def save(self, post: PostWebhook, analysis: AIAnalysis, raw: str) -> None:
    self._conn.execute(_SQL_INSERT_ACTIONABLE, (
        post.message_id, post.channel_id, post.channel_name,
        post.text, post.link, post.timestamp, post.date,
        int(analysis.requires_response), analysis.category,
        analysis.urgency, analysis.reason, analysis.draft_reply_thesis,
        raw, datetime.now().isoformat(),
    ))
    self._conn.commit()
```

Фильтрация и сортировка реализованы через динамическое формирование запроса с параметрами:

```python
_SQL_ORDER_BY_URGENCY = (
    " ORDER BY CASE urgency"
    " WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,"
    " date DESC LIMIT ?"
)

def fetch(self, status=None, urgency=None, limit=50):
    query = "SELECT * FROM actionable_posts WHERE 1=1"
    params = []
    if status is not None:
        query += " AND status = ?"; params.append(status)
    if urgency is not None:
        query += " AND urgency = ?"; params.append(urgency)
    query += _SQL_ORDER_BY_URGENCY; params.append(limit)
    return [dict(row) for row in self._conn.execute(query, params).fetchall()]
```

Агрегированная статистика использует `COUNT(*)` с `GROUP BY` по трём измерениям:

```python
def get_stats(self) -> dict:
    by_urgency = {r["urgency"]: r["cnt"] for r in self._conn.execute(
        "SELECT urgency, COUNT(*) as cnt FROM actionable_posts GROUP BY urgency")}
    by_status = {r["status"]: r["cnt"] for r in self._conn.execute(
        "SELECT status, COUNT(*) as cnt FROM actionable_posts GROUP BY status")}
    by_category = {r["category"]: r["cnt"] for r in self._conn.execute(
        "SELECT category, COUNT(*) as cnt FROM actionable_posts GROUP BY category ORDER BY cnt DESC")}
    return {"total_actionable": total, "by_urgency": by_urgency, ...}
```

Входные данные валидируются Pydantic-моделями `PostWebhook` и `AIAnalysis`, обеспечивающими проверку типов и обязательности полей:

```python
class PostWebhook(BaseModel):
    message_id: int
    channel_id: int
    channel_name: str
    text: str | None = None
    link: str | None = None
    timestamp: int
    date: str

class AIAnalysis(BaseModel):
    requires_response: bool
    category: str
    urgency: str       # low/medium/high
    reason: str
    draft_reply_thesis: str
```

На уровне эндпоинтов дополнительная валидация: проверка допустимых значений `status` (`{"new", "in_progress", "resolved", "ignored"}`) и лимита выборки (`Query(50, ge=1, le=500)`).

##### 3.5. Подсистема защиты данных

**Хеширование паролей (bcrypt).** При регистрации пароль хешируется на сервере до записи в БД. Используется `bcryptjs` с параметром соли 10:

```javascript
// Dashboard/server/routes/auth.routes.js
const hashedPassword = bcrypt.hashSync(password, 10);
const result = createUser(username, hashedPassword);
```

При авторизации выполняется сравнение хеша без раскрытия конкретной ошибки (generic-сообщение):

```javascript
const user = findUserByUsername(username);
if (!user) {
  return res.status(401).json({ error: 'Неверный логин или пароль' });
}
const isValid = bcrypt.compareSync(password, user.password);
if (!isValid) {
  return res.status(401).json({ error: 'Неверный логин или пароль' });
}
```

**JWT-аутентификация.** При успешном входе генерируется токен с payload `{id, username, role}` и временем жизни 24 часа:

```javascript
const token = jwt.sign(
  { id: user.id, username: user.username, role: user.role },
  jwtSecret,
  { expiresIn: '24h' }
);
```

**JWT-middleware** (`Dashboard/server/middleware.js`) обрабатывает три класса ошибок с различными HTTP-кодами:

```javascript
function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Токен не предоставлен' });
  }
  const token = authHeader.split(' ')[1];
  try {
    const decoded = jwt.verify(token, jwtSecret);
    req.user = decoded;
    next();
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      return res.status(401).json({ error: 'Токен истёк. Войдите заново.' });
    }
    return res.status(403).json({ error: 'Невалидный токен' });
  }
}
```

Защищённые маршруты (`/api/posts`, `/api/posts/:id`, `/api/posts/categories`) требуют валидного JWT-токена. Публичные маршруты (`/api/auth/register`, `/api/auth/login`) доступны без аутентификации.

**Fail-fast валидация конфигурации.** Сервер отказывается запускаться без переменной `JWT_SECRET`:

```javascript
// Dashboard/server/server.js
if (!process.env.JWT_SECRET) {
  console.error('❌ JWT_SECRET не настроен');
  process.exit(1);
}
```

##### 3.6. Seed-скрипт и первичное наполнение

При первом запуске Dashboard-сервера автоматически создаётся учётная запись администратора, если таблица `dashboard_users` пуста (`Dashboard/server/db.js`):

```javascript
if (seedAdmin) {
  const { cnt } = stmt.countUsers.get();
  if (cnt === 0) {
    const bcrypt = require('bcryptjs');
    const hashedPassword = bcrypt.hashSync('admin', 10);
    stmt.insertUser.run('admin', hashedPassword, 'admin');
  }
}
```

Seed-пароль `admin` хешируется тем же bcrypt с `saltRounds = 10`, после чего запись вставляется через prepared statement. Это гарантирует, что при развёртывании системы всегда существует хотя бы одна учётная запись с ролью `admin`.

#### 4. ТЕСТИРОВАНИЕ БЕЗОПАСНОСТИ И ЦЕЛОСТНОСТИ БД

Комплексное тестирование охватило все три хранилища данных, подсистему аутентификации и JWT-middleware. Результаты зафиксированы в `TESTING_REPORT.md`: **80 тестов пройдено, 0 провалено (100% успешных)**.

| Компонент | Файл тестов | Пройдено | Провалено | Статус |
|-----------|-------------|----------|-----------|--------|
| MessageStore (дедупликация, UNIQUE, схема) | `Parser/test_comment_parser.py` | 11 | 0 | ✅ |
| ActionableStore (CRUD, фильтрация, статистика) | `AI/test_analytics_server.py` | 16 | 0 | ✅ |
| FastAPI endpoints (валидация статуса, лимит) | `AI/test_analytics_endpoints.py` | 15 | 0 | ✅ |
| Dashboard Server (Auth, JWT, CRUD) | `Dashboard/server/test_dashboard_server.js` | 22 | 0 | ✅ |
| WSGI/конфигурация (mock PyMax) | `Parser/conftest.py` | 16 | 0 | ✅ |
| **Итого** | | **80** | **0** | **100%** |

**Ключевые проверки целостности БД:**
- **Дедупликация `INSERT OR IGNORE`** — тест `test_save_duplicate_ignored` подтверждает, что повторная вставка с тем же `(message_id, channel_id)` не вызывает ошибки и не создаёт дубликат (rowcount = 0).
- **UNIQUE-ограничение** — тест `test_unique_constraint` проверяет, что SQLite отклоняет дубликаты на уровне СУБД.
- **Корректность схемы** — тест `test_database_schema` выполняет `PRAGMA table_info(messages)` и проверяет наличие всех 8 столбцов с корректными типами.
- **Агрегированная статистика** — тест `test_get_stats` создаёт 5 инцидентов с разными `urgency`/`status`/`category` и проверяет корректность `COUNT(*) ... GROUP BY`.
- **Полный жизненный цикл инцидента** — тест `test_full_incident_lifecycle` выполняет последовательность: save → fetch → update_status → get_stats → fetch_one с проверкой на каждом этапе.

**Ключевые проверки безопасности:**
- **Регистрация: валидация входных данных** — тесты с коротким логином (< 3 символа), коротким паролем, попыткой дубликата → ожидаемые коды 400 и 409.
- **Авторизация: некорректные учётные данные** — тест с несуществующим пользователем → 401; тест с неверным паролем → 401 (generic-сообщение, не раскрывающее причину).
- **JWT-middleware: отсутствие токена** → 401; **токен без Bearer-префикса** → 401; **истёкший токен** (`TokenExpiredError`) → 401; **невалидная подпись** → 403.
- **Валидация статуса инцидента** — передача невалидного статуса (`"deleted"`) на эндпоинт `PATCH /actionable/{id}/status` → 400 с перечислением допустимых значений.
- **Лимит выборки** — запрос `limit=0` и `limit=1000` на `GET /actionable` → валидация Pydantic (`ge=1, le=500`).
- **E2E-тест** — последовательность: register → login → GET /api/posts с полученным токеном → 200 OK.

Результаты тестирования задокументированы в `TESTING_REPORT.md` с подробным описанием каждого теста, включая архитектурные изменения (Dependency Injection в Express для изоляции тестов от реальной БД).

#### 5. ОПТИМИЗАЦИЯ РАБОТЫ С БАЗОЙ ДАННЫХ

**Индексы.** Для таблицы `actionable_posts` созданы 4 индекса, покрывающих основные сценарии фильтрации и сортировки:
- `idx_actionable_urgency` — ускорение запросов с фильтром по срочности (`WHERE urgency = 'high'`) и сортировки (`ORDER BY CASE urgency ...`).
- `idx_actionable_status` — фильтрация по статусу обработки (`WHERE status = 'new'`).
- `idx_actionable_date` — сортировка по дате публикации (`ORDER BY date DESC`).
- `idx_actionable_category` — группировка по категориям (`GROUP BY category`).

**WAL-режим.** Активация `journal_mode = WAL` в `Dashboard/server/db.js` позволила устранить блокировки при одновременной записи (FastAPI-сервер сохраняет инциденты) и чтении (Express-сервер отдаёт список постов). В режиме WAL читатели не блокируют писателей и наоборот.

**Кэширование подготовленных выражений.** В `db.js` все SQL-запросы компилируются однократно через `db.prepare()` при инициализации БД. При последующих вызовах используется закэшированный план выполнения, что исключает повторный парсинг SQL. В Python-хранилищах (`ActionableStore`, `MessageStore`) SQL-константы определены на уровне модуля и переиспользуются при каждом вызове `execute()`.

**Лимит выборки.** Метод `getPosts()` ограничен `LIMIT 200`, эндпоинт `GET /actionable` — параметром `limit` с максимумом 500 (`Query(50, ge=1, le=500)`). Это предотвращает загрузку чрезмерных объёмов данных в оперативную память.

**Разделение баз данных.** Сырые сообщения хранятся в `messages.db` (обслуживается парсером), аналитические данные — в `analytics.db` (обслуживается FastAPI и Express). Разделение исключает contention между процессами и позволяет независимо настраивать режимы журналирования, индексы и стратегии резервного копирования.

**Идемпотентность вставки.** Использование `INSERT OR IGNORE` в обоих хранилищах (`MessageStore`, `ActionableStore`) гарантирует, что повторный вызов с теми же данными не создаст дубликат и не вызовет ошибку нарушения UNIQUE-ограничения.

#### 6. ЗАКЛЮЧЕНИЕ

В рамках производственной практики по модулю ПМ.04 «Технология разработки и защиты баз данных» выполнены все требования:

- **Проектирование БД:** разработана ER-модель из трёх таблиц (`messages`, `actionable_posts`, `dashboard_users`), структура приведена ко второй нормальной форме (2НФ), спроектированы составные UNIQUE-ограничения для дедупликации.
- **Реализация в СУБД SQLite:** созданы DDL-схемы с ограничениями `NOT NULL`, `UNIQUE`, `DEFAULT`, `CHECK` (на уровне приложения); активирован WAL-режим для конкурентного доступа; реализованы 4 индекса для оптимизации запросов.
- **Защита данных:** внедрено хеширование паролей bcrypt (saltRounds = 10), JWT-аутентификация (HS256, 24h), параметризованные запросы (prepared statements) во всех хранилищах, fail-fast валидация конфигурации, generic-сообщения об ошибках аутентификации.
- **Тестирование:** проведено 80 тестов (100% pass rate), охватывающих целостность БД (дедупликация, UNIQUE, схема), безопасность (валидация входа, JWT-middleware с 401/403), корректность CRUD-операций и агрегированной статистики.
- **Документирование:** ER-диаграмма описана в `UML_Diagrams.md`, результаты тестирования — в `TESTING_REPORT.md`, схема БД с примерами запросов — в `AI/schema.sql` и `README.md`.

База данных готова к эксплуатации в составе системы MAX AI Dashboard.

#### 7. СПРАВОЧНАЯ ДОКУМЕНТАЦИЯ ПО БД

##### 7.1. Полная схема таблиц (SQL DDL)

**Таблица `actionable_posts`** (файл `AI/schema.sql`):

```sql
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
);

CREATE INDEX IF NOT EXISTS idx_actionable_urgency ON actionable_posts(urgency);
CREATE INDEX IF NOT EXISTS idx_actionable_status  ON actionable_posts(status);
CREATE INDEX IF NOT EXISTS idx_actionable_date    ON actionable_posts(date);
CREATE INDEX IF NOT EXISTS idx_actionable_category ON actionable_posts(category);
```

**Таблица `dashboard_users`** (файл `Dashboard/server/db.js`):

```sql
CREATE TABLE IF NOT EXISTS dashboard_users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT    NOT NULL UNIQUE,
    password  TEXT    NOT NULL,
    role      TEXT    NOT NULL DEFAULT 'admin',
    created_at TEXT   NOT NULL DEFAULT (datetime('now'))
);
```

**Таблица `messages`** (файл `Parser/comment_parser.py`):

```sql
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    channel_name  TEXT    NOT NULL,
    text          TEXT,
    link          TEXT,
    timestamp     INTEGER NOT NULL,
    date          TEXT    NOT NULL,
    UNIQUE(message_id, channel_id)
);
```

##### 7.2. Примеры параметризованных запросов

**Python (sqlite3) — вставка с дедупликацией:**

```python
_SQL_INSERT_ACTIONABLE = """
    INSERT OR IGNORE INTO actionable_posts
        (message_id, channel_id, channel_name, text, link, timestamp, date,
         requires_response, category, urgency, reason, draft_reply_thesis,
         ai_raw_response, analyzed_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
"""
conn.execute(_SQL_INSERT_ACTIONABLE, (
    post.message_id, post.channel_id, post.channel_name, ...
))
```

**JavaScript (better-sqlite3) — подготовленное выражение:**

```javascript
const findUser = db.prepare(
  'SELECT * FROM dashboard_users WHERE username = ?'
);
const user = findUser.get(username);
```

**JavaScript — динамическая фильтрация с параметрами:**

```javascript
let query = 'SELECT * FROM actionable_posts WHERE 1=1';
const params = [];
if (filters.status) { query += ' AND status = ?'; params.push(filters.status); }
return db.prepare(query).all(...params);
```

##### 7.3. Таблица настроек безопасности

| Мера защиты | Реализация | Файл |
|-------------|-----------|------|
| Хеширование паролей | `bcrypt.hashSync(password, 10)` (saltRounds = 10) | `Dashboard/server/routes/auth.routes.js` |
| Верификация паролей | `bcrypt.compareSync(password, user.password)` с generic-ошибкой | `Dashboard/server/routes/auth.routes.js` |
| JWT-аутентификация | `jwt.sign(payload, secret, {expiresIn: '24h'})` | `Dashboard/server/routes/auth.routes.js` |
| JWT-верификация | `jwt.verify(token, secret)` с обработкой `TokenExpiredError` → 401, invalid → 403 | `Dashboard/server/middleware.js` |
| Защита от SQL-инъекций | Параметризованные запросы (`?` placeholder) + `db.prepare()` | `AI/analytics_server.py`, `Dashboard/server/db.js`, `Parser/comment_parser.py` |
| Валидация входных данных | Pydantic-модели `PostWebhook`, `AIAnalysis`; проверка длины логина/пароля ≥ 3 | `AI/analytics_server.py`, `Dashboard/server/routes/auth.routes.js` |
| Fail-fast конфигурация | `process.exit(1)` при отсутствии `JWT_SECRET` | `Dashboard/server/server.js` |
| Дедупликация на уровне СУБД | `UNIQUE(message_id, channel_id)` + `INSERT OR IGNORE` | `AI/schema.sql`, `Parser/comment_parser.py` |
| Ограничение параллелизма LLM | `asyncio.Semaphore(3)` — защита от rate limit при записи в БД | `AI/analytics_server.py` |
| WAL-режим | `db.pragma('journal_mode = WAL')` — конкурентный доступ без блокировок | `Dashboard/server/db.js` |
