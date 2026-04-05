"""
Парсер сообщений из каналов MAX (UserBot) + вебхук на сервер аналитики.

Периодически опрашивает каналы, сохраняет в SQLite и отправляет
каждый новый пост на FastAPI-сервер для AI-анализа.

Конфигурация загружается из файла .env.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv
from pymax import MaxClient

# =============================================================================
# ЗАГРУЗКА .env
# =============================================================================

_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

_logger = logging.getLogger("channel_parser")


def _env(key: str, default: str = "") -> str:
    """Получить переменную окружения с дефолтом."""
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    """Получить boolean из окружения."""
    return _env(key, str(default)).lower() in ("true", "1", "yes", "on")


def _env_int(key: str, default: int = 0) -> int:
    """Получить int из окружения."""
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_list_int(key: str) -> list[int]:
    """Распарсить список int из строки через запятую.

    Пример: '-71887474716883,-71409355871569' → [-71887474716883, -71409355871569]
    """
    raw = _env(key, "").strip()
    if not raw:
        return []

    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            _logger.warning("Пропущен невалидный ID канала: %s", part)
    return ids


# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

CFG_PHONE = _env("PHONE", "+79933283681")
CFG_WORK_DIR = _env("WORK_DIR", "./cache")
CFG_DB_PATH = _env("DB_PATH", "./messages.db")
CFG_POLL_INTERVAL = _env_int("POLL_INTERVAL", 30)
CFG_FETCH_BACKWARD = _env_int("FETCH_BACKWARD", 5)

CFG_WEBHOOK_URL = _env("ANALYTICS_WEBHOOK_URL", "http://127.0.0.1:8000/webhook/post")
CFG_WEBHOOK_TIMEOUT = _env_int("WEBHOOK_TIMEOUT", 15)
CFG_WEBHOOK_RETRIES = _env_int("WEBHOOK_RETRIES", 2)
CFG_WEBHOOK_RETRY_DELAY = _env_int("WEBHOOK_RETRY_DELAY", 5)
CFG_WEBHOOK_FAIL_SAFE = _env_bool("WEBHOOK_FAIL_SAFE", True)

CFG_CHANNEL_IDS: list[int] = _env_list_int("TARGET_CHANNEL_IDS")
CFG_LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, CFG_LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# =============================================================================
# ТИПЫ ДАННЫХ
# =============================================================================

@dataclass(frozen=True, slots=True)
class MessageData:
    """Структурированные данные одного сообщения."""

    message_id: int
    channel_id: int
    channel_name: str
    text: str | None
    link: str
    timestamp: int
    date: str

    def to_webhook_payload(self) -> dict[str, Any]:
        """Сериализация в JSON для отправки на сервер аналитики."""
        return {
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "text": self.text,
            "link": self.link,
            "timestamp": self.timestamp,
            "date": self.date,
        }


# =============================================================================
# БАЗА ДАННЫХ
# =============================================================================

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

_SQL_LAST_MESSAGE_ID = (
    "SELECT MAX(message_id) FROM messages WHERE channel_id = ?"
)

_SQL_INSERT_MESSAGE = """
    INSERT OR IGNORE INTO messages
        (message_id, channel_id, channel_name, text, link, timestamp, date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
"""


class MessageStore:
    """Thread-unsafe SQLite-хранилище сообщений (используется в одном event loop)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = self._init_db()

    # -- инициализация -------------------------------------------------------

    def _init_db(self) -> sqlite3.Connection:
        """Создаёт подключение и схему."""
        conn = sqlite3.connect(self._db_path)
        conn.execute(_SQL_CREATE_MESSAGES)
        conn.commit()
        _logger.info("База данных: %s", self._db_path)
        return conn

    # -- публичный API --------------------------------------------------------

    def get_last_message_id(self, channel_id: int) -> int:
        """Вернуть ID последнего сохранённого сообщения канала."""
        row = self._conn.execute(_SQL_LAST_MESSAGE_ID, (channel_id,)).fetchone()
        return row[0] or 0

    def save(self, msg: MessageData) -> bool:
        """Сохранить сообщение.

        Returns:
            True если запись была вставлена (не существовала ранее).
        """
        try:
            cursor = self._conn.execute(_SQL_INSERT_MESSAGE, (
                msg.message_id,
                msg.channel_id,
                msg.channel_name,
                msg.text,
                msg.link,
                msg.timestamp,
                msg.date,
            ))
            self._conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            _logger.error("Ошибка БД: %s", e)
            self._conn.rollback()
            return False

    def close(self) -> None:
        """Закрыть подключение."""
        self._conn.close()


# =============================================================================
# ВЕБХУК-КЛИЕНТ
# =============================================================================

class WebhookClient:
    """Асинхронный клиент для отправки вебхуков на сервер аналитики.

    Использует один переиспользуемый aiohttp.ClientSession (keep-alive,
    пул соединений).
    """

    def __init__(
        self,
        url: str,
        timeout: int = 15,
        retries: int = 2,
        retry_delay: int = 5,
        fail_safe: bool = True,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._retries = retries
        self._retry_delay = retry_delay
        self._fail_safe = fail_safe
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> WebhookClient:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self._timeout),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._session:
            await self._session.close()

    async def send(self, msg: MessageData) -> dict[str, Any] | None:
        """Отправить сообщение на сервер аналитики.

        Returns:
            Ответ сервера или None при ошибке / rate limit.
        """
        payload = msg.to_webhook_payload()

        for attempt in range(1, self._retries + 1):
            result = await self._try_send(payload, attempt)
            if result is not ...:  # sentinel: отправлено или окончательно провалено
                return result  # type: ignore[return-value]

            if attempt < self._retries:
                await asyncio.sleep(self._retry_delay)

        _logger.error(
            "❌ Вебхук не доставлен после %d попыток (пост #%d)",
            self._retries, payload["message_id"],
        )
        if not self._fail_safe:
            raise RuntimeError("Webhook delivery failed")
        return None

    # -- внутренняя логика ----------------------------------------------------

    async def _try_send(self, payload: dict, attempt: int) -> dict | None | type[...]:
        """Попытка отправки.

        Returns:
            dict   — успешный ответ сервера
            None   — окончательно провалено (4xx, rate limit)
            ...    — нужно ретраить (5xx, таймаут, conn error)
        """
        assert self._session is not None
        try:
            async with self._session.post(self._url, json=payload) as resp:
                if resp.status == 200:
                    return await self._handle_200(resp, payload)
                if resp.status == 429:
                    _logger.info("⏳ Rate limit сервера: #%d", payload["message_id"])
                    return None
                return await self._handle_error(resp, payload)

        except asyncio.TimeoutError:
            _logger.warning("⏱️ Таймаут вебхука (попытка %d/%d)", attempt, self._retries)
            return ...
        except aiohttp.ClientError as e:
            _logger.warning("🌐 Ошибка соединения (попытка %d/%d): %s", attempt, self._retries, e)
            return ...
        except Exception as e:
            _logger.error("❌ Неожиданная ошибка вебхука: %s", e)
            return ...

    async def _handle_200(self, resp: aiohttp.ClientResponse, payload: dict) -> dict | None:
        """Обработка HTTP 200."""
        result = await resp.json()
        if result.get("status") == "rate_limited":
            _logger.info("⏳ AI пропуск (rate limit): #%d", payload["message_id"])
            return None
        _logger.info(
            "🤖 AI: requires_response=%s | category=%s | urgency=%s",
            result.get("requires_response"),
            result.get("category"),
            result.get("urgency"),
        )
        return result

    async def _handle_error(self, resp: aiohttp.ClientResponse, payload: dict) -> dict | None | type[...]:
        """Обработка HTTP-ошибок."""
        body = await resp.text()
        _logger.warning(
            "⚠️ Вебхук #%d: HTTP %d | %s",
            payload["message_id"], resp.status, body[:200],
        )
        if resp.status >= 500:
            return ...  # ретраить
        return None  # 4xx — не ретраим


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def _build_message_link(chat_id: int, message_id: int) -> str:
    """Сформировать ссылку на сообщение."""
    return f"https://max.me/c/{chat_id}/{message_id}"


def _extract_message_data(message: Any, channel_name: str, msg_id: int) -> MessageData:
    """Извлечь данные из PyMax Message в MessageData."""
    if message.link is not None:
        link = (
            f"https://max.me/c/{message.link.chat_id}/{message.link.message.id}"
        )
    else:
        link = _build_message_link(message.chat_id or 0, msg_id)

    ts = message.time
    if ts and ts > 1e12:
        ts /= 1000

    date_str = datetime.fromtimestamp(ts).isoformat() if ts else "unknown"

    return MessageData(
        message_id=msg_id,
        channel_id=message.chat_id or 0,
        channel_name=channel_name,
        text=message.text.strip() if message.text else None,
        link=link,
        timestamp=int(ts) if ts else 0,
        date=date_str,
    )


# =============================================================================
# ПАРСЕР
# =============================================================================

class ChannelParser:
    """Парсер каналов через polling с отправкой вебхуков.

    Lifecycle:
        1. connect → авторизация MAX
        2. resolve_channels → список каналов
        3. poll_loop → бесконечный опрос
        4. disconnect → cleanup
    """

    def __init__(
        self,
        phone: str,
        target_channel_ids: list[int],
        db_path: str,
        work_dir: str = "./cache",
        saved_token: str | None = None,
        poll_interval: int = 30,
        fetch_backward: int = 5,
        webhook_url: str = "http://127.0.0.1:8000/webhook/post",
        webhook_timeout: int = 15,
        webhook_retries: int = 2,
        webhook_retry_delay: int = 5,
        webhook_fail_safe: bool = True,
    ) -> None:
        self._phone = phone
        self._target_channel_ids = target_channel_ids
        self._poll_interval = poll_interval
        self._fetch_backward = fetch_backward

        # Компоненты
        self._store = MessageStore(db_path)
        self._webhook = WebhookClient(
            url=webhook_url,
            timeout=webhook_timeout,
            retries=webhook_retries,
            retry_delay=webhook_retry_delay,
            fail_safe=webhook_fail_safe,
        )

        # Кэш
        self._channel_cache: dict[int, str] = {}
        self._last_ids: dict[int, int] = {}

        # MAX-клиент
        client_kwargs: dict[str, Any] = {
            "phone": phone,
            "work_dir": work_dir,
            "reconnect": True,
            "reconnect_delay": 5.0,
            "logger": _logger,
        }
        if saved_token:
            client_kwargs["token"] = saved_token
        self._client = MaxClient(**client_kwargs)

        # Счётчики
        self._total_fetched = 0
        self._total_saved = 0
        self._total_webhooks_sent = 0
        self._total_webhooks_failed = 0

    # -- публичный API --------------------------------------------------------

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

    # -- startup / shutdown ---------------------------------------------------

    def _log_startup(self) -> None:
        """Лог параметров запуска."""
        _logger.info("🚀 Запуск парсера (polling, интервал %ds)...", self._poll_interval)
        _logger.info("   Телефон:     %s", self._phone)
        _logger.info("   Каналы:      %s", self._target_channel_ids or "ВСЕ")
        _logger.info("   БД:          %s", self._store._db_path)
        _logger.info("   Вебхук:      %s", self._webhook._url)

    def _log_stats(self) -> None:
        """Лог итоговой статистики."""
        _logger.info(
            "📊 Забрано=%d | Сохранено=%d | Вебхуки=%d (ошибки=%d)",
            self._total_fetched,
            self._total_saved,
            self._total_webhooks_sent,
            self._total_webhooks_failed,
        )

    async def _client_close(self) -> None:
        """Безопасное закрытие MAX-клиента."""
        try:
            if hasattr(self._client, "close"):
                await self._client.close()
        except Exception as e:
            _logger.warning("Ошибка при закрытии клиента: %s", e)

    # -- обработчики событий --------------------------------------------------

    def register_handlers(self) -> None:
        """Зарегистрировать все обработчики на MAX-клиенте."""

        @self._client.on_start
        async def _on_startup() -> None:
            await self._handle_startup()

    async def _handle_startup(self) -> None:
        """Логика при успешной авторизации."""
        me = self._client.me
        assert me is not None
        name = me.names[0].first_name if me.names else "Unknown"
        _logger.info("=" * 60)
        _logger.info("✅ Авторизация: %s (ID: %d)", name, me.id)
        _logger.info("=" * 60)

        channels = self._resolve_target_channels()
        if not channels:
            _logger.error("❌ Нет каналов для парсинга!")
            self._client._stop_event.set()
            return

        _logger.info("📡 Буду парсить каналов (%d): %s", len(channels), channels)

        # Инициализация кэшей
        for cid in channels:
            await self._resolve_channel_name(cid)
            self._last_ids[cid] = self._store.get_last_message_id(cid)

        _logger.info("📋 Стартовые позиции в БД: %s", self._last_ids)

        asyncio.create_task(self._poll_loop(channels))

    # -- разрешение каналов ---------------------------------------------------

    def _resolve_target_channels(self) -> list[int]:
        """Определить список каналов для парсинга."""
        if self._target_channel_ids:
            return list(self._target_channel_ids)

        all_channels = self._client.channels
        if not all_channels:
            _logger.warning("⚠️ Каналы не найдены")
            return []

        _logger.info("📋 Все доступные каналы (%d):", len(all_channels))
        _logger.info("%-12s  %-25s  %s", "ID", "USERNAME", "НАЗВАНИЕ")
        _logger.info("-" * 70)

        ids: list[int] = []
        for ch in all_channels:
            username = (ch.link or "").lstrip("@").split("/")[-1] or "—"
            title = ch.title or "без названия"
            cid = getattr(ch, "id", None) or getattr(ch, "id_", None) or 0
            _logger.info("%-12d  @%-24s  %s", cid, username, title)
            ids.append(cid)

        _logger.info("-" * 70)
        return ids

    async def _resolve_channel_name(self, chat_id: int) -> str:
        """Получить и закэшировать название канала."""
        if chat_id in self._channel_cache:
            return self._channel_cache[chat_id]

        try:
            chat = await self._client.get_chat(chat_id)
            name = chat.title if chat else f"channel_{chat_id}"
        except Exception:
            name = f"channel_{chat_id}"

        self._channel_cache[chat_id] = name
        return name

    # -- polling --------------------------------------------------------------

    async def _poll_loop(self, channel_ids: list[int]) -> None:
        """Бесконечный цикл опроса каналов."""
        _logger.info("🔄 Polling запущен (интервал %ds)", self._poll_interval)

        stop_event = self._client._stop_event

        while not stop_event.is_set():
            try:
                for cid in channel_ids:
                    await self._poll_channel(cid)
                _logger.info("💤 Сон %ds...", self._poll_interval)
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                _logger.error("Ошибка polling цикла: %s", e, exc_info=True)
                await asyncio.sleep(5)

    async def _poll_channel(self, channel_id: int) -> None:
        """Опросить один канал и обработать новые сообщения."""
        try:
            last_id = self._last_ids.get(channel_id, 0)
            channel_name = self._channel_cache.get(channel_id, f"channel_{channel_id}")

            messages = await self._client.fetch_history(
                chat_id=channel_id,
                backward=self._fetch_backward,
            )
            if not messages:
                return

            self._total_fetched += len(messages)

            # Фильтр новых (msg.id — строка)
            new_messages = [m for m in messages if int(m.id) > last_id]
            if not new_messages:
                return

            new_messages.sort(key=lambda m: int(m.id))

            # Пакетная обработка
            pending_webhooks: list[asyncio.Task[None]] = []

            for msg in new_messages:
                msg_id = int(msg.id)
                data = _extract_message_data(msg, channel_name, msg_id)

                if self._store.save(data):
                    self._total_saved += 1
                    preview = (data.text or "")[:60] or "(нет текста)"
                    _logger.info("💾 #%d | %s | %s", msg_id, channel_name, preview)
                    pending_webhooks.append(
                        asyncio.create_task(self._send_webhook_safe(data)),
                    )

                if msg_id > self._last_ids.get(channel_id, 0):
                    self._last_ids[channel_id] = msg_id

            # Ждём завершения всех вебхуков (не блокируя следующий polling)
            if pending_webhooks:
                await asyncio.gather(*pending_webhooks, return_exceptions=True)

            _logger.info(
                "✅ Канал %d: +%d новых (всего: %d)",
                channel_id, len(new_messages), self._total_saved,
            )

        except Exception as e:
            _logger.error("Ошибка опроса канала %d: %s", channel_id, e, exc_info=True)

    async def _send_webhook_safe(self, data: MessageData) -> None:
        """Отправить вебхук с подсчётом статистики."""
        try:
            result = await self._webhook.send(data)
            if result:
                self._total_webhooks_sent += 1
            else:
                self._total_webhooks_failed += 1
        except Exception as e:
            _logger.error("Ошибка вебхука: %s", e)
            self._total_webhooks_failed += 1


# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

async def _main() -> None:
    parser = ChannelParser(
        phone=CFG_PHONE,
        target_channel_ids=CFG_CHANNEL_IDS,
        db_path=CFG_DB_PATH,
        work_dir=CFG_WORK_DIR,
        poll_interval=CFG_POLL_INTERVAL,
        fetch_backward=CFG_FETCH_BACKWARD,
        webhook_url=CFG_WEBHOOK_URL,
        webhook_timeout=CFG_WEBHOOK_TIMEOUT,
        webhook_retries=CFG_WEBHOOK_RETRIES,
        webhook_retry_delay=CFG_WEBHOOK_RETRY_DELAY,
        webhook_fail_safe=CFG_WEBHOOK_FAIL_SAFE,
    )

    parser.register_handlers()
    await parser.run()


if __name__ == "__main__":
    asyncio.run(_main())
