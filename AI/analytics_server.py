"""
Сервер аналитики городской администрации (FastAPI).

Принимает вебхуки от парсера MAX, анализирует посты через OpenRouter LLM,
сохраняет инциденты, требующие реакции, в SQLite.

Конфигурация загружается из файла .env.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# =============================================================================
# ЗАГРУЗКА .env
# =============================================================================

_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

_logger = logging.getLogger("analytics_server")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

CFG_SERVER_HOST = _env("SERVER_HOST", "0.0.0.0")
CFG_SERVER_PORT = _env_int("SERVER_PORT", 8000)
CFG_DB_PATH = _env("DB_PATH", "./analytics.db")
CFG_LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()

CFG_OPENROUTER_KEY = _env("OPENROUTER_API_KEY", "")
CFG_OPENROUTER_MODEL = _env("OPENROUTER_MODEL", "qwen/qwen3.6-plus:free")
CFG_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CFG_OPENROUTER_TIMEOUT = _env_int("OPENROUTER_TIMEOUT", 30)

# Connection recovery parameters for LLM
CFG_LLM_CONNECTION_CHECK_INTERVAL = _env_int("LLM_CONNECTION_CHECK_INTERVAL", 60)
CFG_LLM_MAX_RECONNECT_ATTEMPTS = _env_int("LLM_MAX_RECONNECT_ATTEMPTS", 3)
CFG_LLM_RECONNECT_BASE_DELAY = _env_int("LLM_RECONNECT_BASE_DELAY", 2)
CFG_LLM_RECONNECT_MAX_DELAY = _env_int("LLM_RECONNECT_MAX_DELAY", 60)
CFG_LLM_HEALTH_CHECK_TIMEOUT = _env_int("LLM_HEALTH_CHECK_TIMEOUT", 10)

# Ограничение параллельных запросов к LLM (защита от rate limit)
CFG_LLM_MAX_CONCURRENT = 3

logging.basicConfig(
    level=getattr(logging, CFG_LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# =============================================================================
# PYDANTIC-МОДЕЛИ
# =============================================================================

class PostWebhook(BaseModel):
    """Входящий вебхук от парсера."""

    message_id: int
    channel_id: int
    channel_name: str
    text: str | None = None
    link: str | None = None
    timestamp: int
    date: str


class AIAnalysis(BaseModel):
    """Структурированный ответ от LLM."""

    requires_response: bool = Field(description="Требуется ли реакция администрации")
    category: str = Field(description="Категория проблемы")
    urgency: str = Field(description="Уровень срочности: low/medium/high")
    reason: str = Field(description="Обоснование решения")
    draft_reply_thesis: str = Field(description="Тезис для ответа")


# =============================================================================
# БАЗА ДАННЫХ
# =============================================================================

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

_SQL_INSERT_ACTIONABLE = """
    INSERT OR IGNORE INTO actionable_posts
        (message_id, channel_id, channel_name, text, link, timestamp, date,
         requires_response, category, urgency, reason, draft_reply_thesis,
         ai_raw_response, analyzed_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
"""

_SQL_SELECT_ACTIONABLE = """
    SELECT * FROM actionable_posts WHERE 1=1
"""

_SQL_ORDER_BY_URGENCY = (
    " ORDER BY CASE urgency"
    " WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,"
    " date DESC LIMIT ?"
)


class ActionableStore:
    """SQLite-хранилище инцидентов."""

    def __init__(self, db_path: str) -> None:
        self._conn = self._init(db_path)

    @staticmethod
    def _init(db_path: str) -> sqlite3.Connection:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(_SQL_CREATE_ACTIONABLE)
        for stmt in _SQL_INDEXES:
            conn.execute(stmt)
        conn.commit()
        _logger.info("База данных инициализирована: %s", db_path)
        return conn

    def save(self, post: PostWebhook, analysis: AIAnalysis, raw: str) -> None:
        """Сохранить инцидент."""
        try:
            self._conn.execute(_SQL_INSERT_ACTIONABLE, (
                post.message_id,
                post.channel_id,
                post.channel_name,
                post.text,
                post.link,
                post.timestamp,
                post.date,
                int(analysis.requires_response),
                analysis.category,
                analysis.urgency,
                analysis.reason,
                analysis.draft_reply_thesis,
                raw,
                datetime.now().isoformat(),
            ))
            self._conn.commit()
            _logger.info(
                "🚨 ИНЦИДЕНТ сохранён: #%d | %s | срочность=%s | категория=%s",
                post.message_id, post.channel_name,
                analysis.urgency, analysis.category,
            )
        except sqlite3.Error as e:
            _logger.error("Ошибка записи инцидента: %s", e)
            self._conn.rollback()

    def fetch(
        self,
        status: str | None = None,
        urgency: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Получить список инцидентов с фильтрацией."""
        query = _SQL_SELECT_ACTIONABLE
        params: list[Any] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if urgency is not None:
            query += " AND urgency = ?"
            params.append(urgency)

        query += _SQL_ORDER_BY_URGENCY
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def fetch_one(self, message_id: int) -> dict[str, Any] | None:
        """Получить один инцидент по ID сообщения."""
        row = self._conn.execute(
            "SELECT * FROM actionable_posts WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_status(self, message_id: int, status: str) -> int:
        """Обновить статус инцидента.

        Returns:
            Количество изменённых строк.
        """
        cursor = self._conn.execute(
            "UPDATE actionable_posts SET status = ? WHERE message_id = ?",
            (status, message_id),
        )
        self._conn.commit()
        return cursor.rowcount

    def get_stats(self) -> dict[str, Any]:
        """Статистика по инцидентам."""
        total = self._conn.execute(
            "SELECT COUNT(*) FROM actionable_posts"
        ).fetchone()[0]

        by_urgency = {
            r["urgency"]: r["cnt"] for r in self._conn.execute(
                "SELECT urgency, COUNT(*) as cnt FROM actionable_posts GROUP BY urgency"
            ).fetchall()
        }
        by_status = {
            r["status"]: r["cnt"] for r in self._conn.execute(
                "SELECT status, COUNT(*) as cnt FROM actionable_posts GROUP BY status"
            ).fetchall()
        }
        by_category = {
            r["category"]: r["cnt"] for r in self._conn.execute(
                "SELECT category, COUNT(*) as cnt FROM actionable_posts"
                " GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
        }

        return {
            "total_actionable": total,
            "by_urgency": by_urgency,
            "by_status": by_status,
            "by_category": by_category,
        }

    def close(self) -> None:
        self._conn.close()


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """\
Ты — AI-аналитик городской администрации города-курорта. Твоя задача — анализировать \
публикации из Telegram-каналов и определять, требует ли пост реакции со стороны \
городской администрации.

КРИТЕРИИ, КОГДА РЕАКЦИЯ НУЖНА (requires_response: true):
1. ЖКХ: проблемы с водоснабжением, канализацией, электроснабжением, отоплением, \
   вывозом мусора, содержанием дворовых территорий.
2. Инфраструктура: ямы на дорогах, broken тротуары, неработающее освещение, \
   проблемы с общественным транспортом, парковками, дорожными знаками.
3. Благоустройство: состояние парков, пляжей, набережных, детских площадок, \
   зеленых насаждений, чистота улиц.
4. Безопасность: аварийные здания, упавшие деревья, открытые люки, \
   опасные объекты, проблемы в курортной/центральной зоне.
5. Чрезвычайные ситуации: Происшествия, ДТП с пострадавшими, пожары, \
   подтопления, оползни.
6. Открытые вопросы к власти: прямые обращения к администрации, запросы \
   о планах ремонта/стройки, вопросы о городском бюджете/распоряжениях.
7. Экология: загрязнение рек/моря, несанкционированные свалки, \
   вырубка деревьев, загрязнение воздуха.

КРИТЕРИИ, КОГДА РЕАКЦИЯ НЕ НУЖНА (requires_response: false):
- Новости федерального уровня (не касающиеся города напрямую).
- Рекламные посты, анонсы мероприятий без жалоб.
- Личные мнения без конкретной проблемы.
- Юмор, мемы, флуд.
- Посты без текста (только фото/видео без контекста проблемы).
- Политические новости, не связанные с городской инфраструктурой.

КАТЕГОРИИ (category): выбери одну из:
"ЖКХ", "Дороги", "Благоустройство", "Безопасность", "ЧП", "Экология", \
"Транспорт", "Обращение к власти", "Другое"

СРОЧНОСТЬ (urgency):
- "high": ЧП, угроза жизни/здоровью, массовая проблема, критическая инфраструктура
- "medium": проблема влияет на комфорт жителей, требует внимания в течение дней
- "low": пожелание, плановая проблема, не срочный вопрос

ВАЖНО:
- Город-курорт: приоритет — центральные/курортные зоны, пляжи, набережные, туристическая инфраструктура.
- Если пост о другом городе — requires_response: false.
- Если текста мало или нет — requires_response: false.

ОТВЕТ: Верни СТРОГО JSON без markdown-обёрток, без пояснений, без ```json. \
Только один JSON-объект со схемой:
{
    "requires_response": true/false,
    "category": "одна из категорий",
    "urgency": "low" | "medium" | "high",
    "reason": "краткое обоснование (1-2 предложения)",
    "draft_reply_thesis": "тезис для ответа администрации (1 предложение)"
}
"""


# =============================================================================
# OPENROUTER-КЛИЕНТ
# =============================================================================

class LLMClient:
    """Клиент к OpenRouter API с ограничением параллелизма (semaphore) и автоматическим восстановлением соединения."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 30,
        max_concurrent: int = 3,
        connection_check_interval: int = 60,
        max_reconnect_attempts: int = 3,
        reconnect_base_delay: int = 2,
        reconnect_max_delay: int = 60,
        health_check_timeout: int = 10,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client: httpx.AsyncClient | None = None
        
        # Connection health tracking
        self._connection_check_interval = connection_check_interval
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._health_check_timeout = health_check_timeout
        self._last_successful_request = 0
        self._connection_errors = 0
        self._reconnect_attempts = 0
        self._client_created_at = 0

    async def __aenter__(self) -> LLMClient:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._client_created_at = time.time()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    async def analyze(self, text: str) -> AIAnalysis:
        """Проанализировать текст поста через LLM.

        Raises:
            httpx.HTTPStatusError — ошибка API
            ValueError — невалидный JSON или структура ответа
        """
        async with self._semaphore:
            # Проверяем здоровье соединения перед запросом
            await self._ensure_connection_health()
            return await self._request(text)

    async def _request(self, text: str) -> AIAnalysis:
        assert self._client is not None

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

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://max-parser.local",
            "X-Title": "Max Parser Analytics",
        }

        try:
            resp = await self._client.post(CFG_OPENROUTER_URL, json=payload, headers=headers)
            resp.raise_for_status()

            data = resp.json()

            if "choices" not in data:
                error_info = data.get("error", data)
                _logger.error("OpenRouter ответил без 'choices': %s", error_info)
                raise ValueError(f"Unexpected OpenRouter response: {error_info}")

            content = data["choices"][0]["message"]["content"]
            result = self._parse_response(content)
            
            # Успешный запрос - сбрасываем счетчики ошибок
            self._connection_errors = 0
            self._last_successful_request = time.time()
            self._reconnect_attempts = 0
            
            return result
            
        except httpx.HTTPStatusError as e:
            self._connection_errors += 1
            if e.response.status_code >= 500:
                _logger.warning("OpenRouter серверная ошибка: %s", e.response.status_code)
                raise
            else:
                # 4xx ошибки - не пытаемся переподключиться
                _logger.error("OpenRouter клиентская ошибка: %s", e.response.status_code)
                raise
        except httpx.RequestError as e:
            self._connection_errors += 1
            _logger.warning("OpenRouter ошибка соединения: %s", e)
            raise

    @staticmethod
    def _parse_response(content: str) -> AIAnalysis:
        """Распарсить и валидировать JSON-ответ LLM."""
        content = content.strip()

        # Убираем markdown-обёртку
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            if content.startswith("json"):
                content = content[4:].strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            _logger.error("LLM вернула невалидный JSON: %s", content[:300])
            raise ValueError(f"Invalid JSON from LLM: {e}") from e

        required = {"requires_response", "category", "urgency", "reason", "draft_reply_thesis"}
        missing = required - set(parsed.keys())
        if missing:
            raise ValueError(f"LLM response missing keys: {missing}")

        # Нормализация urgency
        parsed["urgency"] = parsed["urgency"].lower()
        if parsed["urgency"] not in ("low", "medium", "high"):
            parsed["urgency"] = "medium"

        return AIAnalysis(**parsed)

    async def _ensure_connection_health(self) -> None:
        """Проверить здоровье соединения и восстановить при необходимости."""
        if not self._client:
            return
            
        current_time = time.time()
        client_age = current_time - self._client_created_at
        time_since_success = current_time - self._last_successful_request
        
        # Если клиент старый или много ошибок, проверяем соединение
        need_health_check = (
            (client_age > self._connection_check_interval * 2) or
            (self._connection_errors >= 2) or
            (self._last_successful_request > 0 and time_since_success > self._connection_check_interval * 3)
        )
        
        if need_health_check:
            await self._check_connection_health()
            
        # Если ошибок много, пытаемся переподключиться
        if self._connection_errors >= 3:
            await self._attempt_reconnection()

    async def _check_connection_health(self) -> None:
        """Проверить здоровье соединения с OpenRouter API."""
        try:
            # Легкий health check - пробуем получить модели
            health_client = httpx.AsyncClient(timeout=self._health_check_timeout)
            try:
                resp = await health_client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {self._api_key}"}
                )
                if resp.status_code == 200:
                    _logger.debug("💓 OpenRouter соединение в порядке")
                    self._connection_errors = 0
                else:
                    self._connection_errors += 1
                    _logger.warning("🔍 Health check не прошел: HTTP %d", resp.status_code)
            finally:
                await health_client.aclose()
                
        except Exception as e:
            _logger.warning("🔍 Ошибка health check: %s", e)
            self._connection_errors += 1

    async def _attempt_reconnection(self) -> None:
        """Попытаться переподключиться к OpenRouter API."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            _logger.error("❌ Превышено максимальное количество попыток переподключения LLM (%d)", 
                        self._max_reconnect_attempts)
            return
            
        self._reconnect_attempts += 1
        
        # Экспоненциальный backoff
        delay = min(
            self._reconnect_base_delay * (2 ** (self._reconnect_attempts - 1)),
            self._reconnect_max_delay
        )
        
        _logger.info("🔄 Попытка переподключения LLM %d/%d через %ds", 
                   self._reconnect_attempts, self._max_reconnect_attempts, delay)
        
        try:
            await asyncio.sleep(delay)
            
            # Пересоздаем клиент
            if self._client:
                try:
                    await self._client.aclose()
                except Exception as e:
                    _logger.warning("Ошибка при закрытии LLM клиента: %s", e)
            
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
            self._client_created_at = time.time()
            
            # Проверяем, что новый клиент работает
            await self._check_connection_health()
            
            if self._connection_errors == 0:
                _logger.info("✅ Переподключение LLM успешно")
                self._reconnect_attempts = 0
            
        except Exception as e:
            _logger.error("❌ Попытка переподключения LLM не удалась: %s", e, exc_info=True)
            # Если еще есть попытки, планируем следующую
            if self._reconnect_attempts < self._max_reconnect_attempts:
                asyncio.create_task(self._attempt_reconnection())


# =============================================================================
# FASTAPI-ПРИЛОЖЕНИЕ
# =============================================================================

# Глобальные компоненты (инициализируются в lifespan)
_store: ActionableStore | None = None
_llm: LLMClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Инициализация и shutdown приложения."""
    global _store, _llm

    if not CFG_OPENROUTER_KEY or CFG_OPENROUTER_KEY.startswith("sk-or-v1-YOUR"):
        _logger.warning("⚠️ OPENROUTER_API_KEY не настроен!")

    _store = ActionableStore(CFG_DB_PATH)

    async with LLMClient(
        api_key=CFG_OPENROUTER_KEY,
        model=CFG_OPENROUTER_MODEL,
        timeout=CFG_OPENROUTER_TIMEOUT,
        max_concurrent=CFG_LLM_MAX_CONCURRENT,
        connection_check_interval=CFG_LLM_CONNECTION_CHECK_INTERVAL,
        max_reconnect_attempts=CFG_LLM_MAX_RECONNECT_ATTEMPTS,
        reconnect_base_delay=CFG_LLM_RECONNECT_BASE_DELAY,
        reconnect_max_delay=CFG_LLM_RECONNECT_MAX_DELAY,
        health_check_timeout=CFG_LLM_HEALTH_CHECK_TIMEOUT,
    ) as llm:
        _llm = llm
        _logger.info(
            "🚀 Сервер аналитики запущен на %s:%d", CFG_SERVER_HOST, CFG_SERVER_PORT,
        )
        yield
        _llm = None

    if _store:
        _store.close()
        _store = None
    _logger.info("Сервер остановлен")


app = FastAPI(
    title="Max Parser Analytics",
    description="Аналитический пайплайн для оценки постов MAX",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.post("/webhook/post")
async def receive_post(post: PostWebhook) -> dict[str, Any]:
    """Принять пост от парсера, проанализировать через LLM."""
    _logger.info(
        "📨 Вебхук: #%d | %s | %s",
        post.message_id, post.channel_name,
        (post.text or "")[:60] or "(нет текста)",
    )

    if not post.text or not post.text.strip():
        return {"status": "skipped", "reason": "no text"}

    assert _llm is not None, "LLM client not initialized"

    try:
        analysis = await _llm.analyze(post.text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            _logger.warning("⏳ Rate limit OpenRouter — пост #%d пропущен", post.message_id)
            return {
                "status": "rate_limited",
                "requires_response": None,
                "reason": "OpenRouter rate limit exceeded",
            }
        _logger.error("OpenRouter API error: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"LLM API error: {e.response.status_code}",
        )
    except ValueError as e:
        _logger.error("LLM parsing error: %s", e)
        raise HTTPException(status_code=500, detail=f"Invalid LLM response: {e}")
    except Exception as e:
        _logger.error("Unexpected error analyzing post: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during analysis")

    if analysis.requires_response:
        assert _store is not None
        raw_response = json.dumps({
            "requires_response": analysis.requires_response,
            "category": analysis.category,
            "urgency": analysis.urgency,
            "reason": analysis.reason,
            "draft_reply_thesis": analysis.draft_reply_thesis,
        })
        _store.save(post, analysis, raw_response)

    return {
        "status": "analyzed",
        "requires_response": analysis.requires_response,
        "category": analysis.category,
        "urgency": analysis.urgency,
        "reason": analysis.reason,
    }


@app.get("/actionable")
async def get_actionable_posts(
    status: str | None = Query(None),
    urgency: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Получить список инцидентов с фильтрацией."""
    assert _store is not None
    return _store.fetch(status=status, urgency=urgency, limit=limit)


@app.get("/actionable/{message_id}")
async def get_actionable_post(message_id: int) -> dict[str, Any]:
    """Получить конкретный инцидент."""
    assert _store is not None
    result = _store.fetch_one(message_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return result


@app.patch("/actionable/{message_id}/status")
async def update_post_status(message_id: int, status: str) -> dict[str, Any]:
    """Обновить статус инцидента."""
    valid = {"new", "in_progress", "resolved", "ignored"}
    if status not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid}",
        )

    assert _store is not None
    affected = _store.update_status(message_id, status)
    if affected == 0:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"status": "ok", "message_id": message_id, "new_status": status}


@app.get("/stats")
async def get_stats() -> dict[str, Any]:
    """Статистика по инцидентам."""
    assert _store is not None
    return _store.get_stats()


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Проверка работоспособности с детальной информацией."""
    health_info = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "analytics_server",
        "version": "1.0.0",
        "components": {}
    }
    
    # Проверяем базу данных
    try:
        if _store:
            stats = _store.get_stats()
            health_info["components"]["database"] = {
                "status": "ok",
                "total_actionable": stats["total_actionable"]
            }
        else:
            health_info["components"]["database"] = {"status": "not_initialized"}
    except Exception as e:
        health_info["components"]["database"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Проверяем LLM клиент
    try:
        if _llm:
            health_info["components"]["llm"] = {
                "status": "ok",
                "model": CFG_OPENROUTER_MODEL,
                "connection_errors": _llm._connection_errors,
                "last_successful_request": _llm._last_successful_request,
                "reconnect_attempts": _llm._reconnect_attempts
            }
        else:
            health_info["components"]["llm"] = {"status": "not_initialized"}
    except Exception as e:
        health_info["components"]["llm"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Определяем общий статус
    component_statuses = [comp.get("status", "unknown") for comp in health_info["components"].values()]
    if any(status in ["error", "not_initialized"] for status in component_statuses):
        health_info["status"] = "degraded"
    
    return health_info


@app.get("/health/ready")
async def readiness_check() -> dict[str, str]:
    """Проверка готовности сервиса к работе."""
    if not _store or not _llm:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    # Проверяем, что база данных работает
    try:
        _store.get_stats()
    except Exception:
        raise HTTPException(status_code=503, detail="Database not ready")
    
    return {"status": "ready", "timestamp": datetime.now().isoformat()}


@app.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """Проверка, что сервис запущен."""
    return {"status": "alive", "timestamp": datetime.now().isoformat()}


# =============================================================================
# ЗАПУСК
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    log_level = CFG_LOG_LEVEL.lower()
    if log_level not in ("debug", "info", "warning", "error", "critical"):
        log_level = "info"

    uvicorn.run(
        "analytics_server:app",
        host=CFG_SERVER_HOST,
        port=CFG_SERVER_PORT,
        reload=False,
        log_level=log_level,
    )
