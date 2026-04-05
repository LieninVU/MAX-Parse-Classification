-- ============================================================================
-- SQL схема таблицы actionable_posts
-- Хранит посты, требующие реакции городской администрации
-- ============================================================================

CREATE TABLE IF NOT EXISTS actionable_posts (
    -- Первичный ключ
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- ═══ Оригинальные данные поста ═══
    message_id          INTEGER NOT NULL,       -- ID сообщения в системе MAX
    channel_id          INTEGER NOT NULL,       -- Числовой ID канала
    channel_name        TEXT    NOT NULL,       -- Название канала (title)
    text                TEXT,                   -- Текст сообщения (может быть NULL)
    link                TEXT,                   -- Прямая ссылка на сообщение
    timestamp           INTEGER NOT NULL,       -- UNIX-время публикации (секунды)
    date                TEXT    NOT NULL,       -- ISO-формат даты (YYYY-MM-DDTHH:MM:SS)

    -- ═══ Вердикт AI ═══
    requires_response   INTEGER NOT NULL,       -- 1 = требуется реакция, 0 = нет
    category            TEXT    NOT NULL,       -- Категория: ЖКХ/Дороги/Благоустройство/Безопасность/ЧП/Экология/Транспорт/Обращение к власти/Другое
    urgency             TEXT    NOT NULL,       -- low / medium / high
    reason              TEXT    NOT NULL,       -- Обоснование решения (1-2 предложения)
    draft_reply_thesis  TEXT,                   -- Тезис для ответа администрации (1 предложение)

    -- ═══ Мета ═══
    ai_raw_response     TEXT,                   -- Сырой JSON-ответ от LLM (для отладки)
    analyzed_at         TEXT    NOT NULL,       -- ISO-дата времени анализа
    status              TEXT    NOT NULL DEFAULT 'new',  -- new / in_progress / resolved / ignored

    -- Уникальность: один пост = один инцидент
    UNIQUE(message_id, channel_id)
);

-- Индексы для ускорения фильтрации
CREATE INDEX IF NOT EXISTS idx_actionable_urgency ON actionable_posts(urgency);
CREATE INDEX IF NOT EXISTS idx_actionable_status  ON actionable_posts(status);
CREATE INDEX IF NOT EXISTS idx_actionable_date    ON actionable_posts(date);
CREATE INDEX IF NOT EXISTS idx_actionable_category ON actionable_posts(category);

-- ============================================================================
-- Примеры запросов
-- ============================================================================

-- Все новые инциденты высокой срочности
-- SELECT * FROM actionable_posts WHERE status = 'new' AND urgency = 'high' ORDER BY date DESC;

-- Статистика по категориям
-- SELECT category, COUNT(*) as cnt FROM actionable_posts GROUP BY category ORDER BY cnt DESC;

-- Инциденты за последние 24 часа
-- SELECT * FROM actionable_posts WHERE analyzed_at >= datetime('now', '-24 hours') ORDER BY urgency, date DESC;

-- Среднее количество инцидентов в день
-- SELECT date(analyzed_at) as day, COUNT(*) as incidents FROM actionable_posts GROUP BY day ORDER BY day DESC LIMIT 7;
