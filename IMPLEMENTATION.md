РЕАЛИЗАЦИЯ
Разработанная система представляет собой автоматизированный пайплайн мониторинга мессенджера MAX для выявления инцидентов, требующих реакции городской администрации. Архитектура построена по модели трёх независимых сервисов, работающих с общей SQLite-базой. Парсер сообщений реализован на Python (PyMax + aiohttp), AI-анализатор — на Python (FastAPI + OpenRouter LLM), сервер дашборда — на Node.js (Express + better-sqlite3), а пользовательский интерфейс — на React 19 + Vite + Tailwind CSS 4.

Структура проекта:
Parser/
    comment_parser.py
    requirements.txt
    .env.example

AI/
    analytics_server.py
    run_server.py
    schema.sql
    requirements.txt
    .env.example

Dashboard/
    server/
        server.js
        db.js
        middleware.js
        routes/
            auth.routes.js
            post.routes.js
        package.json
        .env.example
    client/
        src/
            App.jsx
            main.jsx
            index.css
            context/
                AuthContext.jsx
            lib/
                api.js
            components/
                ProtectedRoute.jsx
            pages/
                Login.jsx
                Register.jsx
                Dashboard.jsx
        package.json

Проект разделён на три независимых процесса, которые запускаются отдельно и координируют работу через файлы SQLite. Парсер (Parser/comment_parser.py) опрашивает каналы мессенджера MAX и отправляет вебхуки на AI-сервер (AI/analytics_server.py). AI-сервер анализирует каждый пост через LLM OpenRouter и сохраняет инциденты в analytics.db. Сервер дашборда (Dashboard/server/) и клиентское приложение (Dashboard/client/) читают эту же базу данных, предоставляя администраторам веб-интерфейс для управления инцидентами.

1. Модуль парсинга каналов MAX
    async def run(self) -> None:
        """Запустить парсер с graceful shutdown."""
        async with self._webhook:
            try:
                self._log_startup()
                await self._client.start()
            except KeyboardInterrupt:
                _logger.info("⏹ Остановка...")
            except Exception as e:
                _logger.critical("Критическая ошибка: %s", e, exc_info=True)
            finally:
                self._log_stats()
                self._store.close()
                await self._client_close()
                _logger.info("Завершено.")

    async def _handle_startup(self) -> None:
        """Логика при успешной авторизации."""
        me = self._client.me
        name = me.names[0].first_name if me.names else "Unknown"
        channels = self._resolve_target_channels()
        for cid in channels:
            await self._resolve_channel_name(cid)
            self._last_ids[cid] = self._store.get_last_message_id(cid)
        asyncio.create_task(self._poll_loop(channels))

    async def _poll_loop(self, channel_ids: list[int]) -> None:
        """Бесконечный цикл опроса каналов."""
        while not stop_event.is_set():
            for cid in channel_ids:
                await self._poll_channel(cid)
            await asyncio.sleep(self._poll_interval)

    async def _poll_channel(self, channel_id: int) -> None:
        """Опросить один канал и обработать новые сообщения."""
        messages = await self._client.fetch_history(
            chat_id=channel_id, backward=self._fetch_backward,
        )
        new_messages = [m for m in messages if int(m.id) > last_id]
        for msg in new_messages:
            data = _extract_message_data(msg, channel_name, msg_id)
            if self._store.save(data):
                pending_webhooks.append(
                    asyncio.create_task(self._send_webhook_safe(data)),
                )
            if msg_id > self._last_ids.get(channel_id, 0):
                self._last_ids[channel_id] = msg_id

Модуль парсинга реализован в comment_parser.py. При запуске парсер авторизуется в мессенджере MAX через библиотеку PyMax по номеру телефона из .env. Если в TARGET_CHANNEL_IDS указан список каналов, парсер работает только с ними, иначе разрешает все доступные каналы и выводит их список в лог.

Цикл опроса работает каждые 30 секунд (настраивается через POLL_INTERVAL). Для каждого канала загружаются последние 5 сообщений (FETCH_BACKWARD). Новые сообщения отбираются по условию message_id > last_saved, где last_saved берётся из SQLite. Дедупликация обеспечивается через UNIQUE(message_id, channel_id) и INSERT OR IGNORE.

Каждое успешно сохранённое сообщение отправляется вебхуком на AI-сервер через WebhookClient. Клиент использует один переиспользуемый aiohttp.ClientSession с keep-alive. При отправке предусмотрено 2 retry-попытки с задержкой 5 секунд. Если AI-сервер недоступен, парсер не падает (WEBHOOK_FAIL_SAFE=True) — это ключевое свойство отказоустойчивости.

Результаты парсинга сохраняются в messages.db — базу сырых сообщений, которая содержит 8 полей и используется как локальный лог всех обработанных постов.

2. Модуль инициализации базы данных парсера
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

class MessageStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute(_SQL_CREATE_MESSAGES)
        conn.commit()
        return conn

    def get_last_message_id(self, channel_id: int) -> int:
        row = self._conn.execute(_SQL_LAST_MESSAGE_ID, (channel_id,)).fetchone()
        return row[0] or 0

    def save(self, msg: MessageData) -> bool:
        cursor = self._conn.execute(_SQL_INSERT_MESSAGE, (
            msg.message_id, msg.channel_id, msg.channel_name,
            msg.text, msg.link, msg.timestamp, msg.date,
        ))
        self._conn.commit()
        return cursor.rowcount > 0

Хранилище сообщений MessageStore инкапсулирует работу с messages.db. При инициализации создаётся таблица messages, если её ещё нет. Метод get_last_message_id возвращает максимальный ID сообщения для канала, что позволяет парсеру при перезапуске продолжить опрос с нужной позиции.

Метод save использует INSERT OR IGNORE, что гарантирует идемпотентность: одно и то же сообщение не будет вставлено дважды, даже если парсер перезапустился и заново опрашивает канал.

3. Модуль AI-анализа через LLM
SYSTEM_PROMPT = """\
Ты — AI-аналитик городской администрации города-курорта. Твоя задача — анализировать \
публикации из Telegram-каналов и определять, требует ли пост реакции со стороны \
городской администрации.

КРИТЕРИИ, КОГДА РЕАКЦИЯ НУЖНА (requires_response: true):
1. ЖКХ: проблемы с водоснабжением, канализацией, электроснабжением, отоплением...
2. Инфраструктура: ямы на дорогах, broken тротуары, неработающее освещение...
3. Благоустройство: состояние парков, пляжей, набережных...
4. Безопасность: аварийные здания, упавшие деревья, открытые люки...
5. Чрезвычайные ситуации: Происшествия, ДТП с пострадавшими, пожары...
6. Открытые вопросы к власти: прямые обращения к администрации...
7. Экология: загрязнение рек/моря, несанкционированные свалки...

КАТЕГОРИИ (category): "ЖКХ", "Дороги", "Благоустройство", "Безопасность", \
"ЧП", "Экология", "Транспорт", "Обращение к власти", "Другое"

СРОЧНОСТЬ (urgency):
- "high": ЧП, угроза жизни/здоровью, массовая проблема
- "medium": проблема влияет на комфорт жителей
- "low": пожелание, плановая проблема
"""

class LLMClient:
    async def analyze(self, text: str) -> AIAnalysis:
        async with self._semaphore:
            return await self._request(text)

    async def _request(self, text: str) -> AIAnalysis:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Проанализируй пост:\n\n{text}"},
            ],
            "temperature": 0.1,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        resp = await self._client.post(CFG_OPENROUTER_URL, json=payload, headers=headers)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return self._parse_response(content)

    @staticmethod
    def _parse_response(content: str) -> AIAnalysis:
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        parsed["urgency"] = parsed["urgency"].lower()
        if parsed["urgency"] not in ("low", "medium", "high"):
            parsed["urgency"] = "medium"
        return AIAnalysis(**parsed)

Модуль AI-анализа расположен в analytics_server.py. При получении вебхука от парсера сервер сначала проверяет наличие текста — пустые посты пропускаются. Затем текст отправляется в OpenRouter API с использованием модели qwen/qwen3.6-plus:free.

Системный промпт определяет роль AI как аналитика городской администрации города-курорта. Модель классифицирует пост по 9 категориям и 3 уровням срочности, формирует обоснование решения и тезис ответа администрации. Temperature установлен на 0.1 для детерминированных результатов, max_tokens — 500.

Для защиты от rate limit используется asyncio.Semaphore на 3 параллельных запроса. При ответе 429 от OpenRouter пост пропускается с логированием. Ответ LLM парсится с учётом возможной markdown-обёртки ```json. Если urgency не соответствует допустимым значениям, он нормализуется к "medium".

4. Эндпоинт приёма вебхуков и маршрутизация
@app.post("/webhook/post")
async def receive_post(post: PostWebhook) -> dict[str, Any]:
    """Принять пост от парсера, проанализировать через LLM."""
    if not post.text or not post.text.strip():
        return {"status": "skipped", "reason": "no text"}

    try:
        analysis = await _llm.analyze(post.text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"status": "rate_limited", "reason": "OpenRouter rate limit"}
        raise HTTPException(status_code=502, detail=f"LLM API error: {e.response.status_code}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Invalid LLM response: {e}")

    if analysis.requires_response:
        raw_response = json.dumps({...})
        _store.save(post, analysis, raw_response)

    return {
        "status": "analyzed",
        "requires_response": analysis.requires_response,
        "category": analysis.category,
        "urgency": analysis.urgency,
    }

@app.get("/actionable")
async def get_actionable_posts(
    status: str | None = Query(None),
    urgency: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:

@app.patch("/actionable/{message_id}/status")
async def update_post_status(message_id: int, status: str) -> dict[str, Any]:
    valid = {"new", "in_progress", "resolved", "ignored"}
    if status not in valid:
        raise HTTPException(status_code=400, detail="Invalid status")
    affected = _store.update_status(message_id, status)
    return {"status": "ok", "message_id": message_id, "new_status": status}

@app.get("/stats")
async def get_stats() -> dict[str, Any]:
    return _store.get_stats()

Эндпоинт POST /webhook/post — основной маршрут для приёма постов от парсера. Входящие данные валидируются через Pydantic-модель PostWebhook. Если пост требует реакции (requires_response=true), он сохраняется в analytics.db. Парсер получает ответ с результатами анализа и логирует их.

Эндпоинт GET /actionable возвращает список инцидентов с фильтрацией по статусу и срочности. Сортировка всегда идёт по убыванию срочности (high → medium → low), затем по дате. Лимит по умолчанию 50, максимум 500.

Эндпоинт PATCH /actionable/{message_id}/status позволяет обновить статус инцидента. Допустимые значения: new, in_progress, resolved, ignored.

Эндпоинт GET /stats возвращает агрегированную статистику: общее количество инцидентов, распределение по срочности, статусу и категориям.

5. Модуль базы данных AI-сервера
_SQL_CREATE_ACTIONABLE = """
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
"""

_SQL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_actionable_urgency ON actionable_posts(urgency)",
    "CREATE INDEX IF NOT EXISTS idx_actionable_status  ON actionable_posts(status)",
    "CREATE INDEX IF NOT EXISTS idx_actionable_date    ON actionable_posts(date)",
)

class ActionableStore:
    def save(self, post: PostWebhook, analysis: AIAnalysis, raw: str) -> None:
        self._conn.execute(_SQL_INSERT_ACTIONABLE, (
            post.message_id, post.channel_id, post.channel_name,
            post.text, post.link, post.timestamp, post.date,
            int(analysis.requires_response), analysis.category,
            analysis.urgency, analysis.reason, analysis.draft_reply_thesis,
            raw, datetime.now().isoformat(),
        ))
        self._conn.commit()

    def fetch(self, status=None, urgency=None, limit=50) -> list[dict]:
        query = _SQL_SELECT_ACTIONABLE
        params = []
        if status: query += " AND status = ?"; params.append(status)
        if urgency: query += " AND urgency = ?"; params.append(urgency)
        query += _ORDER_BY_URGENCY
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) FROM actionable_posts").fetchone()[0]
        by_urgency = {...}
        by_status = {...}
        by_category = {...}
        return {"total_actionable": total, "by_urgency": by_urgency, ...}

Хранилище ActionableStore управляет таблицей actionable_posts в analytics.db. Таблица содержит 17 полей: оригинальные данные поста, вердикт AI (requires_response, category, urgency, reason, draft_reply_thesis), мета-данные (ai_raw_response для отладки, analyzed_at, status).

Четыре индекса (urgency, status, date, category) ускоряют фильтрацию и сортировку, что критично при работе дашборда, который регулярно запрашивает отфильтрованные данные.

Жизненный цикл хранилища управляется через lifespan-контекст FastAPI: при старте создаётся подключение и таблицы, при завершении — соединение закрывается.

6. Модуль инициализации базы данных дашборда
const SQL_CREATE_USERS = `
  CREATE TABLE IF NOT EXISTS dashboard_users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT    NOT NULL UNIQUE,
    password  TEXT    NOT NULL,
    role      TEXT    NOT NULL DEFAULT 'admin',
    created_at TEXT   NOT NULL DEFAULT (datetime('now'))
  )
`;

const SQL_CREATE_ACTIONABLE = `
  CREATE TABLE IF NOT EXISTS actionable_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL,
    channel_id          INTEGER NOT NULL,
    ...
    UNIQUE(message_id, channel_id)
  )
`;

function initDatabase() {
  db.exec(SQL_CREATE_USERS);
  db.exec(SQL_CREATE_ACTIONABLE);
  SQL_INDEXES.forEach((sql) => db.exec(sql));
  seedDefaultUser();
}

function seedDefaultUser() {
  const { cnt } = stmt.countUsers.get();
  if (cnt === 0) {
    const hashedPassword = bcrypt.hashSync('admin', 10);
    stmt.insertUser.run('admin', hashedPassword, 'admin');
    console.log('✅ Создан пользователь по умолчанию: admin / admin');
  }
}

Модуль db.js выполняет двойную функцию: инициализирует общую базу analytics.db и управляет данными пользователей дашборда. При запуске Express создаются таблицы dashboard_users и actionable_posts (совместимая с FastAPI-схемой), а также четыре индекса для ускорения запросов.

Ключевой особенностью является WAL-режим (db.pragma('journal_mode = WAL')), который позволяет FastAPI и Express одновременно работать с одной базой без блокировок. FastAPI пишет инциденты, Express читает и удаляет их — WAL обеспечивает безопасный конкурентный доступ.

При первом запуске автоматически создаётся пользователь admin с паролем admin (bcrypt hash, salt rounds = 10). Это позволяет сразу начать работу с дашбордом без ручной регистрации.

Все SQL-стейтменты预先 компилируются через db.prepare() и кешируются в объекте stmt — это рекомендация better-sqlite3 для повышения производительности.

7. Модуль авторизации и управления доступом
router.post('/login', (req, res) => {
  const { username, password } = req.body;
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
    process.env.JWT_SECRET,
    { expiresIn: '24h' }
  );
  res.json({ message: 'Вход выполнен', token, user: { id: user.id, username: user.username, role: user.role } });
});

function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Токен не предоставлен' });
  }
  const token = authHeader.split(' ')[1];
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.user = decoded;
    next();
  } catch (err) {
    if (err.name === 'TokenExpiredError') {
      return res.status(401).json({ error: 'Токен истёк. Войдите заново.' });
    }
    return res.status(403).json({ error: 'Невалидный токен' });
  }
}

Модуль авторизации реализован в auth.routes.js и middleware.js. При входе сервер находит пользователя в таблице dashboard_users через预先 подготовленный стейтмент, сверяет пароль с bcrypt-хешем через compareSync. При успешной аутентификации создаётся JWT-токен с payload (id, username, role), срок действия — 24 часа.

Middleware authMiddleware проверяет заголовок Authorization: Bearer <token> на каждом защищённом маршруте. При истечении токена (TokenExpiredError) возвращается 401, при невалидной подписи — 403. Клиентский interceptor в api.js автоматически перехватывает 401 и перенаправляет на страницу входа.

Маршруты авторизации подключены к /api/auth без middleware (публичные), а маршруты работы с постами — к /api/posts с middleware authMiddleware (защищённые).

8. Модуль регистрации пользователей
router.post('/register', (req, res) => {
  const { username, password } = req.body;
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
    return res.status(409).json({ error: 'Пользователь с таким логином уже существует' });
  }
  const hashedPassword = bcrypt.hashSync(password, 10);
  const result = createUser(username, hashedPassword);
  return res.status(201).json({ message: 'Пользователь создан', user: { id: result.lastInsertRowid, username, role: 'admin' } });
});

Открытая регистрация реализована через POST /api/auth/register. Любой пользователь может создать аккаунт с ролью admin. Валидация проверяет минимальную длину логина и пароля (3 символа), а также уникальность username. Пароль хешируется через bcrypt с salt rounds = 10. При попытке зарегистрировать существующего пользователя возвращается HTTP 409 (Conflict).

После успешной регистрации клиент автоматически перенаправляет на страницу входа через 1.5 секунды с сообщением об успехе.

9. Главная страница дашборда и её логика
export default function Dashboard() {
  const { user, logout } = useAuth();
  const [posts, setPosts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [filterCategory, setFilterCategory] = useState('');
  const [filterUrgency, setFilterUrgency] = useState('');

  const fetchPosts = useCallback(async () => {
    const params = {};
    if (filterCategory) params.category = filterCategory;
    if (filterUrgency) params.urgency = filterUrgency;
    const res = await api.get('/posts', { params });
    setPosts(res.data);
  }, [filterCategory, filterUrgency]);

  useEffect(() => { fetchPosts(); }, [fetchPosts]);

  const handleDelete = async (id) => {
    if (!window.confirm('Удалить этот инцидент?')) return;
    await api.delete(`/posts/${id}`);
    setPosts((prev) => prev.filter((p) => p.id !== id));
  };

  return (
    <table>
      {posts.map((post) => (
        <tr>
          <td>#{post.id}</td>
          <td>{post.channel_name}</td>
          <td><div className="truncate">{post.text}</div></td>
          <td>{post.category}</td>
          <td><span className={URGENCY_META[post.urgency].color}>
            {URGENCY_META[post.urgency].label}</span></td>
          <td><span className={STATUS_COLORS[post.status]}>
            {post.status}</span></td>
          <td>{formatDate(post.date)}</td>
          <td><button onClick={() => handleDelete(post.id)}>Удалить</button></td>
        </tr>
      ))}
    </table>
  );
}

Главная страница дашборда реализована в Dashboard.jsx. При загрузке компонент загружает список уникальных категорий через GET /api/posts/categories и инциденты через GET /api/posts. Данные запрашиваются заново при каждом изменении фильтров благодаря useCallback и useEffect.

Таблица отображает 8 колонок: ID, канал, текст (с truncation), категория, срочность, статус, дата, действие. Цветовые бейджи кодируют срочность: высокая — красный (bg-red-100), средняя — жёлтый (bg-yellow-100), низкая — зелёный (bg-green-100). Статусы также имеют цветовую кодировку: new — синий, in_progress — жёлтый, resolved — зелёный, ignored — серый.

Удаление инцидента требует подтверждения через window.confirm. При успешном удалении запись удаляется из локального state без перезагрузки страницы.

10. Модуль фильтрации и сортировки данных
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

Модуль фильтрации расположен в db.js. Запрос динамически строится на основе переданных фильтров (category, urgency, status). Сортировка всегда двухуровневая: сначала по срочности (high → medium → low через CASE-выражение), затем по дате (новые первыми). Лимит жёстко ограничен 200 записями для предотвращения перегрузки интерфейса.

На клиенте фильтры реализованы через два select-элемента: категория загружается из БД динамически, срочность задаётся статичными опциями (высокая/средняя/низкая). Кнопка «Сбросить» очищает оба фильтра, что вызывает повторный запрос без параметров.

11. Модуль JWT-перехватчиков на клиенте
const api = axios.create({ baseURL: '/api', timeout: 15000 });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('dashboard_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('dashboard_token');
      localStorage.removeItem('dashboard_user');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

Модуль api.js централизует работу с API через настроенный экземпляр Axios. Request-interceptor автоматически подставляет Bearer-токен из localStorage в каждый запрос. Response-interceptor перехватывает HTTP 401 (истёкший или невалидный токен) и очищает сессию с перенаправлением на страницу входа.

Такой подход избавляет компоненты от ручной обработки авторизации: Dashboard.jsx просто вызывает api.get('/posts'), а проверка токена и редирект при его истечении происходят прозрачно.

12. Модуль управления контекстом авторизации
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const savedUser = localStorage.getItem('dashboard_user');
    const savedToken = localStorage.getItem('dashboard_token');
    if (savedUser && savedToken) {
      setUser(JSON.parse(savedUser));
    }
    setLoading(false);
  }, []);

  const login = (token, userData) => {
    localStorage.setItem('dashboard_token', token);
    localStorage.setItem('dashboard_user', JSON.stringify(userData));
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem('dashboard_token');
    localStorage.removeItem('dashboard_user');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

Модуль AuthContext.jsx реализует React Context для глобального управления авторизацией. При монтировании провайдера проверяется localStorage: если токен и данные пользователя сохранены, сессия восстанавливается без повторного входа.

Функция login сохраняет токен и userData в localStorage, обновляет state. Функция logout полностью очищает сессию. Поле loading используется ProtectedRoute для отображения индикатора загрузки, пока проверяется localStorage.

13. Модуль защиты приватных маршрутов
export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <div>Загрузка...</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

Модуль ProtectedRoute.jsx — обёртка вокруг react-router-dom, которая проверяет авторизацию перед рендерингом дочерних компонентов. Если пользователь не авторизован, происходит редирект на /login. В состоянии loading отображается индикатор, чтобы избежать мерцания интерфейса.

В App.jsx маршрут /dashboard обёрнут в ProtectedRoute, а маршруты /login и /register доступны публично. При попытке перейти на /dashboard без авторизации пользователь автоматически перенаправляется на страницу входа.

14. Модуль пользовательского интерфейса
Оформление интерфейса реализовано через Tailwind CSS 4. Глобальные стили определены в index.css с импортом @import "tailwindcss". Базовый фон — slate-50 (#f8fafc), текст — slate-900.

Интерфейс разделён на несколько страниц:
- Login.jsx — форма входа с градиентным фоном (slate-800 → slate-900), полями логина и пароля, ссылкой на регистрацию
- Register.jsx — форма регистрации с подтверждением пароля, валидацией на клиенте и авто-редиректом после успеха
- Dashboard.jsx — таблица инцидентов с header-панелью, фильтрами (категория + срочность), цветными бейджами urgencы и статуса, кнопкой удаления и выхода

Vite настроен с proxy: все запросы к /api перенаправляются на Express-сервер (localhost:5000), что позволяет фронтенду работать на порту 3000 без CORS-проблем.

15. Конфигурация и переменные окружения
Каждый компонент настраивается через собственный .env-файл:

Parser/.env:
- PHONE — номер телефона для авторизации в MAX
- TARGET_CHANNEL_IDS — список ID каналов (пусто = все каналы)
- POLL_INTERVAL — интервал опроса (секунды, по умолчанию 30)
- ANALYTICS_WEBHOOK_URL — URL AI-сервера
- WEBHOOK_RETRIES — количество retry-попыток (по умолчанию 2)
- WEBHOOK_FAIL_SAFE — не падать при ошибке вебхука (True)

AI/.env:
- OPENROUTER_API_KEY — ключ API OpenRouter
- OPENROUTER_MODEL — модель LLM (по умолчанию qwen/qwen3.6-plus:free)
- SERVER_HOST, SERVER_PORT — хост и порт FastAPI (0.0.0.0:8000)
- DB_PATH — путь к analytics.db

Dashboard/server/.env:
- JWT_SECRET — секретный ключ для подписи JWT-токенов
- PORT — порт Express-сервера (по умолчанию 5000)
- DB_PATH — путь к общей базе analytics.db

Dashboard/client/vite.config — proxy /api → http://localhost:5000

Все чувствительные данные (ключи API, пароли, JWT-секреты) хранятся исключительно в .env-файлах и не попадают в систему контроля версий благодаря .gitignore.
