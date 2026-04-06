# 🏙️ MAX AI Dashboard — City Incident Monitor

> Автоматическая система мониторинга инцидентов на основе LLM. Собирает публикации из мессенджера **MAX**, анализирует их с помощью AI и определяет, какие жалобы требуют реакции городской администрации.

<p align="center">
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React 19" />
  <img src="https://img.shields.io/badge/Node.js-Express-339933?style=for-the-badge&logo=node.js&logoColor=white" alt="Node.js" />
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite" alt="Vite" />
  <img src="https://img.shields.io/badge/Tailwind-4-06B6D4?style=flat-square&logo=tailwindcss" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/OpenRouter-LLM-FF6D00?style=flat-square" alt="OpenRouter" />
  <img src="https://img.shields.io/badge/JWT-Auth-D40000?style=flat-square" alt="JWT" />
</p>

---

## 📋 Содержание

- [О проекте](#-о-проекте)
- [Архитектура](#-архитектура)
- [Стек технологий](#-стек-технологий)
- [Ключевые фичи](#-ключевые-фичи)
- [Установка и запуск](#-установка-и-локальный-запуск)
- [Переменные окружения](#-переменные-окружения)
- [API Endpoints](#-api-endpoints)
- [Доступные скрипты](#-доступные-скрипты)
- [AI-анализ: категории и срочность](#-ai-анализ-категории-и-срочность)
- [Схема базы данных](#-схема-базы-данных)
- [Обработка ошибок](#-обработка-ошибок)
- [Лицензия](#-лицензия)

---

## 📖 О проекте

Ежедневно тысячи жителей оставляют сообщения в локальных каналах мессенджера MAX — жалобы на прорывы труб, ямы на дорогах, незаконные свалки, аварийные здания. Отслеживать их вручную — трудоёмкая задача, которая требует постоянного мониторинга и субъективной оценки каждого поста.

**MAX AI Dashboard** решает эту проблему, автоматизируя весь пайплайн: от сбора публикаций до классификации инцидентов с помощью Large Language Model (LLM). Система определяет, требует ли пост реакции администрации, присваивает категорию (ЖКХ, Дороги, Экология и т.д.) и уровень срочности, а затем предоставляет удобный веб-интерфейс для работы с отфильтрованными инцидентами.

> **Ключевая идея:** LLM берёт на себя рутину первичной фильтрации, а администратор получает готовую панель с приоритизированными инцидентами, готовыми к передаче в профильные службы.

---

## 🏗 Архитектура

Пайплайн прохождения данных состоит из трёх компонентов:

```
┌──────────────────┐      webhook POST       ┌───────────────────────┐
│   🕷️  Parser     │ ──────────────────────► │   🧠  AI-Анализатор   │
│   (Python)       │                         │   (FastAPI + LLM)     │
│                  │                         │                       │
│  • Polling MAX   │   new message           │  • OpenRouter API     │
│  • Deduplication │ ──────────────────────► │  • Классификация      │
│  • messages.db   │                         │  • analytics.db       │
└──────────────────┘                         └───────────┬───────────┘
                                                        │ shared DB
                                                        ▼
                                       ┌────────────────────────────┐
                                       │   📊  Web Dashboard        │
                                       │   (Express + React)        │
                                       │                            │
                                       │  • JWT-авторизация         │
                                       │  • Фильтрация инцидентов   │
                                       │  • Управление статусами    │
                                       └────────────────────────────┘
```

1. **Parser** подключается к мессенджеру MAX через UserBot API, опрашивает целевые каналы каждые ~30 секунд и сохраняет каждый новый пост в локальную БД (`messages.db`).
2. Каждый **новый пост** отправляется webhook-запросом на **AI-Анализатор**.
3. **AI-Анализатор** вызывает OpenRouter LLM (модель Qwen по умолчанию), которая определяет, требует ли пост реакции администрации, и присваивает категорию + уровень срочности. Инциденты сохраняются в `analytics.db`.
4. **Dashboard Server** (Express) читает ту же `analytics.db` и отдаёт отфильтрованные инциденты через REST API с JWT-аутентификацией.
5. **Dashboard Client** (React + Vite) отображает инциденты в таблице, позволяет фильтровать по категории и срочности, а также удалять записи.

---

## 🛠 Стек технологий

### 🖥 Frontend

| Технология | Назначение |
|---|---|
| **React 19** | UI-фреймворк |
| **Vite 8** | Сборщик и dev-сервер |
| **Tailwind CSS 4** | Стилизация |
| **React Router 7** | Роутинг |
| **Axios** | HTTP-клиент с JWT-интерцептором |

### ⚙️ Backend

| Технология | Назначение |
|---|---|
| **Node.js + Express 5** | REST API сервер дашборда |
| **FastAPI** | AI-анализатор (вебхук + LLM) |
| **better-sqlite3** | Синхронный SQLite-драйвер (Express) |
| **SQLite (aiosqlite)** | Асинхронный SQLite (FastAPI) |
| **JWT (jsonwebtoken)** | Аутентификация |
| **bcryptjs** | Хеширование паролей |

### 🤖 AI / Bot

| Технология | Назначение |
|---|---|
| **maxapi-python** | UserBot API для мессенджера MAX |
| **OpenRouter API** | Шлюз к LLM-моделям |
| **Qwen 3.6 Plus** (free) | LLM по умолчанию |
| **aiohttp** | Async HTTP для парсера |

---

## ✨ Ключевые фичи

- **🔐 JWT-аутентификация** — полная защита API дашборда; токен автоматически прикрепляется к каждому запросу и обновляется при истечении.
- **🤖 AI-классификация** — LLM автоматически определяет категорию (8 категорий), уровень срочности (high/medium/low) и формирует тезис ответа.
- **🔄 Автоматический seeding** — при первом запуске Dashboard Server создаёт аккаунт `admin / admin` (пароль хешируется bcrypt).
- **📊 Фильтрация в реальном времени** — фильтрация по категории, срочности и статусу прямо из веб-интерфейса.
- **🗜 Shared SQLite с WAL** — FastAPI и Express безопасно читают/пишут одну и ту же БД благодаря WAL journal mode.
- **🛡 Отказоустойчивость парсера** — retry логика (2 попытки, 5 сек интервал) и fail-safe режим: парсер не падает при недоступности вебхука.
- **📋 Rate Limiting LLM** — semaphore ограничивает максимум 3 параллельных запроса к OpenRouter, предотвращая 429 ошибки.
- **🎨 Цветовая кодировка** — инциденты визуально маркированы: красный = high, жёлтый = medium, зелёный = low.

---

## 🚀 Установка и локальный запуск

### Prerequisites

| Зависимость | Минимальная версия |
|---|---|
| [Node.js](https://nodejs.org/) | 18+ |
| [npm](https://www.npmjs.com/) | 9+ |
| [Python](https://www.python.org/) | 3.12+ |

### Шаг 1 — Клонирование репозитория

```bash
git clone <your-repo-url>
cd Max_Parser
```

### Шаг 2 — Установка зависимостей парсера

```bash
cd Parser
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

### Шаг 3 — Установка зависимостей AI-сервера

```bash
cd ../AI
pip install -r requirements.txt
```

### Шаг 4 — Установка зависимостей Dashboard

```bash
# Server
cd ../Dashboard/server
npm install

# Client
cd ../client
npm install
```

### Шаг 5 — Настройка переменных окружения

Создайте `.env` файлы на основе `.env.example` в каждой директории (см. раздел ниже).

### Шаг 6 — Запуск компонентов

```bash
# Терминал 1 — AI-Анализатор
cd AI
python run_server.py

# Терминал 2 — Парсер
cd Parser
.venv\Scripts\python comment_parser.py

# Терминал 3 — Dashboard Server
cd Dashboard/server
npm run dev

# Терминал 4 — Dashboard Client
cd Dashboard/client
npm run dev
```

| Компонент | URL | Описание |
|---|---|---|
| AI-Анализатор | `http://127.0.0.1:8000` | FastAPI + Swagger UI (`/docs`) |
| Dashboard Client | `http://localhost:3000` | React приложение (Vite) |
| Dashboard Server | `http://localhost:5000` | Express REST API |

---

## 🔑 Переменные окружения

### Parser — `Parser/.env`

```env
# Аккаунт UserBot
PHONE=+7XXXXXXXXXX

# Целевые каналы (пусто = все каналы)
TARGET_CHANNEL_IDS=

# Директория кеша сессий
WORK_DIR=./cache

# Путь к БД парсера
DB_PATH=./messages.db

# Настройки polling
POLL_INTERVAL=30
FETCH_BACKWARD=5

# Вебхук в AI-сервер
ANALYTICS_WEBHOOK_URL=http://127.0.0.1:8000/webhook/post
WEBHOOK_TIMEOUT=30
WEBHOOK_RETRIES=2
WEBHOOK_RETRY_DELAY=5
WEBHOOK_FAIL_SAFE=true

# Логирование
LOG_LEVEL=INFO
```

### AI Server — `AI/.env`

```env
# OpenRouter API (получите на https://openrouter.ai/keys)
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# LLM-модель (по умолчанию — бесплатная)
OPENROUTER_MODEL=qwen/qwen3.6-plus:free

# Сервер
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Путь к БД (общая с Dashboard)
DB_PATH=./analytics.db

# Логирование
LOG_LEVEL=INFO
```

### Dashboard Server — `Dashboard/server/.env`

```env
# Порт Express-сервера
PORT=5000

# Секретный ключ JWT (обязательно измените в продакшене!)
JWT_SECRET=super-secret-jwt-key-change-me-in-production

# Путь к общей БД (совпадает с AI/analytics.db)
DB_PATH=../../AI/analytics.db
```

> ⚠️ **Никогда не коммитьте `.env` файлы!** Они уже добавлены в `.gitignore`.

---

## 📡 API Endpoints

### AI-Анализатор (FastAPI — порт 8000)

| Method | Endpoint | Описание | Auth |
|---|---|---|---|
| `POST` | `/webhook/post` | Принять пост от парсера, проанализировать через LLM | ❌ |
| `GET` | `/actionable` | Список инцидентов (фильтры: `status`, `urgency`, `limit`) | ❌ |
| `GET` | `/actionable/:message_id` | Конкретный инцидент | ❌ |
| `PATCH` | `/actionable/:message_id/status` | Обновить статус (`new` / `in_progress` / `resolved` / `ignored`) | ❌ |
| `GET` | `/stats` | Статистика по категориям, срочности и статусам | ❌ |
| `GET` | `/health` | Health check | ❌ |

### Dashboard Server (Express — порт 5000)

| Method | Endpoint | Описание | Auth |
|---|---|---|---|
| `POST` | `/api/auth/register` | Регистрация нового пользователя | ❌ |
| `POST` | `/api/auth/login` | Вход, возврат JWT-токена (24h) | ❌ |
| `GET` | `/api/posts` | Инциденты с фильтрацией (`?category=&urgency=&status=`) | ✅ JWT |
| `DELETE` | `/api/posts/:id` | Удалить инцидент | ✅ JWT |
| `GET` | `/api/categories` | Список доступных категорий | ✅ JWT |
| `GET` | `/api/health` | Health check | ❌ |

---

## 📦 Доступные скрипты

### Dashboard Client (Vite)

```bash
cd Dashboard/client

npm run dev        # Запуск dev-сервера (Vite) с HMR
npm run build      # Продакшен-сборка в dist/
npm run preview    # Предпросмотр продакшен-сборки
npm run lint       # ESLint проверка
```

### Dashboard Server (Express)

```bash
cd Dashboard/server

npm run dev        # Запуск с nodemon (--watch, автоперезапуск)
npm start          # Запуск без watch (продакшен)
```

### AI Server (FastAPI)

```bash
cd AI

python run_server.py           # Запуск uvicorn
python analytics_server.py     # Прямой запуск (если нужно)
```

### Parser

```bash
cd Parser

.venv\Scripts\python comment_parser.py   # Запуск парсера
```

---

## 🧠 AI-анализ: категории и срочность

### Категории инцидентов

| Категория | Когда присваивается |
|---|---|
| 🏠 **ЖКХ** | Водоснабжение, канализация, отопление, электричество, мусор |
| 🛣️ **Дороги** | Ямы, тротуары, знаки, светофоры, покрытие |
| 🌳 **Благоустройство** | Парки, пляжи, площадки, озеленение, чистота |
| ⚠️ **Безопасность** | Аварийные здания, упавшие деревья, открытые люки |
| 🚨 **ЧП** | ДТП с пострадавшими, пожары, подтопления |
| 🌿 **Экология** | Загрязнение, свалки, вырубка |
| 🚌 **Транспорт** | Маршруты, расписания, переполненность |
| 📢 **Обращение к власти** | Прямые вопросы к администрации |

### Уровни срочности

| Уровень | Описание | Пример |
|---|---|---|
| 🔴 **high** | Угроза жизни/здоровью, критическая инфраструктура | Прорыв трубы, пожар, ДТП |
| 🟡 **medium** | Влияет на комфорт, требует внимания в течение дней | Яма на дороге, неработающий фонарь |
| 🟢 **low** | Пожелание, плановая проблема | Предложение по благоустройству |

---

## 🗄 Схема базы данных

### `analytics.db` — `actionable_posts`

Общая таблица для FastAPI (запись) и Express (чтение/удаление):

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
    requires_response   INTEGER NOT NULL,       -- 0 или 1
    category            TEXT    NOT NULL,        -- Категория проблемы
    urgency             TEXT    NOT NULL,        -- low / medium / high
    reason              TEXT    NOT NULL,        -- Обоснование AI
    draft_reply_thesis  TEXT,                    -- Тезис ответа
    ai_raw_response     TEXT,                    -- Сырой ответ LLM
    analyzed_at         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'new',
    UNIQUE(message_id, channel_id)
);

CREATE INDEX idx_urgency    ON actionable_posts(urgency);
CREATE INDEX idx_status     ON actionable_posts(status);
CREATE INDEX idx_date       ON actionable_posts(date);
CREATE INDEX idx_category   ON actionable_posts(category);
```

### `analytics.db` — `dashboard_users`

Таблица пользователей для JWT-авторизации:

```sql
CREATE TABLE IF NOT EXISTS dashboard_users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL UNIQUE,
    password    TEXT    NOT NULL,              -- bcrypt хеш
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

---

## ⚠️ Обработка ошибок

| Сценарий | Поведение системы |
|---|---|
| OpenRouter недоступен | HTTP 502, парсер продолжает работу |
| LLM вернула не JSON | HTTP 500, парсер продолжает работу |
| Rate Limit (429) | Semaphore ограничивает до 3 одновременных запросов |
| AI-сервер недоступен | Парсер ретраит 2 раза с интервалом 5 сек |
| Все ретраи исчерпаны | Лог ошибки, парсер **НЕ** останавливается |
| Неверный JWT | HTTP 403 (invalid) / HTTP 401 (expired) → клиент редиректит на `/login` |

---

## 📄 Лицензия

Проект распространяется под лицензией **MIT**. Подробнее — в файле [LICENSE](LICENSE).

---

<p align="center">
  <strong>MAX AI Dashboard</strong> — мониторинг инцидентов на службе города 🏙️
</p>
