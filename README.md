# Аналитический пайплайн MAX Parser + AI

Автоматическая система мониторинга и анализа публикаций из Telegram-каналов
для оценки необходимости реакции городской администрации.

## Архитектура

```
┌─────────────────┐     POST /webhook/post     ┌──────────────────────┐
│   MAX Parser    │ ──────────────────────────► │  Analytics Server   │
│  (comment_      │                            │  (FastAPI + OpenRouter)
│   parser.py)    │                            │                     │
│                 │                            │  ┌───────────────┐  │
│  ┌───────────┐  │                            │  │  LLM Analysis │  │
│  │ messages  │  │         если requires_     │  │  (Claude/GPT) │  │
│  │   (SQLite)│  │         response == true   │  └───────┬───────┘  │
│  └───────────┘  │                            │          │          │
│                 │                            │          ▼          │
│  Polling каждые │                            │  ┌───────────────┐  │
│  30 сек         │                            │  │actionable_posts│  │
│                 │                            │  │   (SQLite)     │  │
└─────────────────┘                            │  └───────────────┘  │
                                               └──────────────────────┘
```

## Структура проекта

```
Max_Parser/
├── Parser/
│   ├── comment_parser.py      # Парсер каналов + вебхук-отправитель
│   ├── messages.db            # Все собранные посты
│   ├── requirements.txt       # Зависимости парсера
│   └── cache/                 # Сессия MAX (session.db)
│
├── AI/
│   ├── analytics_server.py    # FastAPI сервер + OpenRouter интеграция
│   ├── run_server.py          # Скрипт запуска сервера
│   ├── .env.example           # Шаблон конфигурации
│   ├── analytics.db           # Таблица actionable_posts (создаётся автоматически)
│   └── requirements.txt       # Зависимости сервера
│
└── README.md                  # Этот файл
```

## Быстрый старт

### Шаг 1. Установка зависимостей

```bash
# Для парсера
cd Parser
.venv\Scripts\pip install -r requirements.txt

# Для сервера
cd ../AI
pip install -r requirements.txt
```

### Шаг 2. Настройка сервера аналитики

1. Скопируйте `.env.example` → `.env`:
   ```bash
   cp .env.example .env
   ```

2. Получите API-ключ на [openrouter.ai/keys](https://openrouter.ai/keys)

3. Вставьте ключ в `.env`:
   ```
   OPENROUTER_API_KEY=sk-or-v1-ваш_ключ
   ```

### Шаг 3. Запуск сервера

```bash
cd AI
python run_server.py
```

Сервер запустится на `http://0.0.0.0:8000`

### Шаг 4. Запуск парсера

```bash
cd Parser
.venv\Scripts\python comment_parser.py
```

Парсер подключится к MAX, начнёт polling каналов и отправлять каждый новый пост на сервер.

## API Endpoints сервера

### POST /webhook/post
Принимает пост от парсера, анализирует через LLM.

**Request:**
```json
{
    "message_id": 116353656500919771,
    "channel_id": -68562381873183,
    "channel_name": "Сочи - Лазаревское",
    "text": "Жители улицы Ленина жалуются на прорыв трубы...",
    "link": "https://max.me/c/-68562381873183/116353656500919771",
    "timestamp": 1775420425,
    "date": "2026-04-05T23:20:25"
}
```

**Response:**
```json
{
    "status": "analyzed",
    "requires_response": true,
    "category": "ЖКХ",
    "urgency": "high",
    "reason": "Прорыв трубы — критическая проблема ЖКХ, влияет на водоснабжение жителей"
}
```

### GET /actionable
Список инцидентов, требующих реакции.

**Параметры:**
- `status`: new / in_progress / resolved / ignored
- `urgency`: low / medium / high
- `limit`: максимум записей (default 50)

**Response:**
```json
[
    {
        "id": 1,
        "message_id": 116353656500919771,
        "channel_name": "Сочи - Лазаревское",
        "text": "Жители улицы Ленина жалуются...",
        "link": "https://max.me/c/...",
        "requires_response": 1,
        "category": "ЖКХ",
        "urgency": "high",
        "reason": "Прорыв трубы...",
        "draft_reply_thesis": "Бригада направлена на устранение прорыва",
        "status": "new",
        "analyzed_at": "2026-04-05T23:20:30"
    }
]
```

### GET /actionable/{message_id}
Конкретный инцидент.

### PATCH /actionable/{message_id}/status
Обновить статус инцидента.

**Request:** `?status=in_progress`

### GET /stats
Статистика по инцидентам:
```json
{
    "total_actionable": 42,
    "by_urgency": {"high": 5, "medium": 18, "low": 19},
    "by_status": {"new": 12, "in_progress": 8, "resolved": 20, "ignored": 2},
    "by_category": {"ЖКХ": 15, "Дороги": 10, "Благоустройство": 8, ...}
}
```

### GET /health
Проверка работоспособности.

## Система категорий AI

| Категория | Когда присваивается |
|---|---|
| **ЖКХ** | Водоснабжение, канализация, отопление, электричество, мусор |
| **Дороги** | Ямы, тротуары, знаки, светофоры, покрытие |
| **Благоустройство** | Парки, пляжи, площадки, озеленение, чистота |
| **Безопасность** | Аварийные здания, упавшие деревья, открытые люки |
| **ЧП** | ДТП с пострадавшими, пожары, подтопления |
| **Экология** | Загрязнение, свалки, вырубка |
| **Транспорт** | Маршруты, расписания, переполненность |
| **Обращение к власти** | Прямые вопросы к администрации |

## Уровни срочности

| Уровень | Описание | Пример |
|---|---|---|
| **high** | Угроза жизни/здоровью, критическая инфраструктура | Прорыв трубы, пожар, ДТП |
| **medium** | Проблема влияет на комфорт, требует внимания в течение дней | Яма на дороге, неработающий фонарь |
| **low** | Пожелание, плановая проблема | Предложение по благоустройству |

## Схема БД actionable_posts

```sql
CREATE TABLE IF NOT EXISTS actionable_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL,       -- ID сообщения в MAX
    channel_id          INTEGER NOT NULL,       -- ID канала
    channel_name        TEXT    NOT NULL,       -- Название канала
    text                TEXT,                   -- Текст поста
    link                TEXT,                   -- Ссылка на пост
    timestamp           INTEGER NOT NULL,       -- UNIX-время
    date                TEXT    NOT NULL,       -- ISO-дата
    requires_response   INTEGER NOT NULL,       -- 0/1
    category            TEXT    NOT NULL,       -- Категория проблемы
    urgency             TEXT    NOT NULL,       -- low/medium/high
    reason              TEXT    NOT NULL,       -- Обоснование
    draft_reply_thesis  TEXT,                   -- Тезис ответа
    ai_raw_response     TEXT,                   -- Сырой ответ LLM
    analyzed_at         TEXT    NOT NULL,       -- Время анализа
    status              TEXT    NOT NULL DEFAULT 'new',
    UNIQUE(message_id, channel_id)
);
```

## System Prompt для LLM

Полный текст промпта находится в `analytics_server.py` → `SYSTEM_PROMPT`.
Ключевые принципы:
- Роль: AI-аналитик городской администрации города-курорта
- Чёткие критерии когда реакция НУЖНА и когда НЕ нужна
- Приоритет курортных/центральных зон
- Строгий JSON-ответ без лишних символов

## Обработка ошибок

| Сценарий | Поведение |
|---|---|
| OpenRouter недоступен | HTTP 502, парсер продолжает работу |
| LLM вернула не JSON | HTTP 500, парсер продолжает работу |
| Сервер аналитики недоступен | Парсер ретраит 2 раза с интервалом 5 сек |
| Все ретраи исчерпаны | Лог ошибки, парсер НЕ останавливается |

## Примеры использования

### curl — проверить статистику
```bash
curl http://127.0.0.1:8000/stats
```

### curl — получить инциденты высокой срочности
```bash
curl "http://127.0.0.1:8000/actionable?urgency=high&status=new"
```

### curl — обновить статус инцидента
```bash
curl -X PATCH "http://127.0.0.1:8000/actionable/116353656500919771/status?status=in_progress"
```

### Swagger UI
Откройте `http://127.0.0.1:8000/docs` для интерактивной документации.
