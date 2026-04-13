"""
Тесты для Parser — MessageStore, WebhookClient, MessageData.
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# Импортируем из comment_parser
import sys
sys.path.insert(0, str(Path(__file__).parent))

from comment_parser import (
    MessageData,
    MessageStore,
    WebhookClient,
    _build_message_link,
    _extract_message_data,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture()
def test_db_path(tmp_path):
    """Временная база данных для тестов."""
    return str(tmp_path / "test_messages.db")


@pytest.fixture()
def store(test_db_path):
    """Хранилище сообщений с чистой БД."""
    s = MessageStore(test_db_path)
    yield s
    s.close()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def make_message_data(message_id=1, channel_id=100, text="Тест"):
    """Создать MessageData для тестов."""
    return MessageData(
        message_id=message_id,
        channel_id=channel_id,
        channel_name="Test Channel",
        text=text,
        link=f"https://max.me/c/{channel_id}/{message_id}",
        timestamp=int(datetime.now().timestamp()),
        date=datetime.now().isoformat(),
    )


# =============================================================================
# ТЕСТЫ: MessageData
# =============================================================================

class TestMessageData:

    def test_to_webhook_payload(self):
        """Сериализация в webhook payload."""
        msg = make_message_data()
        payload = msg.to_webhook_payload()

        assert payload["message_id"] == msg.message_id
        assert payload["channel_id"] == msg.channel_id
        assert payload["channel_name"] == msg.channel_name
        assert payload["text"] == msg.text
        assert payload["link"] == msg.link
        assert payload["timestamp"] == msg.timestamp
        assert payload["date"] == msg.date

    def test_to_webhook_payload_no_text(self):
        """Сообщение без текста."""
        msg = MessageData(
            message_id=1,
            channel_id=100,
            channel_name="Test",
            text=None,
            link="https://example.com",
            timestamp=1234567890,
            date="2024-01-01T00:00:00",
        )
        payload = msg.to_webhook_payload()
        assert payload["text"] is None

    def test_message_data_is_frozen(self):
        """MessageData — immutable (frozen=True)."""
        msg = make_message_data()
        with pytest.raises(Exception):
            msg.message_id = 999


# =============================================================================
# ТЕСТЫ: MessageStore
# =============================================================================

class TestMessageStore:

    def test_save_and_get_last_id(self, store):
        """Сохранение и получение последнего ID."""
        msg = make_message_data(message_id=10, channel_id=100)
        result = store.save(msg)
        assert result is True

        last_id = store.get_last_message_id(100)
        assert last_id == 10

    def test_save_duplicate_ignored(self, store):
        """Дедупликация: повторная вставка игнорируется."""
        msg = make_message_data(message_id=1, channel_id=100)

        result1 = store.save(msg)
        result2 = store.save(msg)

        assert result1 is True
        assert result2 is False  # INSERT OR IGNORE не вставил

    def test_get_last_id_empty(self, store):
        """Получение последнего ID из пустой таблицы."""
        last_id = store.get_last_message_id(999)
        assert last_id == 0

    def test_save_multiple_messages(self, store):
        """Сохранение нескольких сообщений в одном канале."""
        for i in range(1, 6):
            msg = make_message_data(message_id=i, channel_id=100)
            store.save(msg)

        last_id = store.get_last_message_id(100)
        assert last_id == 5

    def test_save_different_channels(self, store):
        """Разные каналы хранят свои last_message_id."""
        msg1 = make_message_data(message_id=10, channel_id=100)
        msg2 = make_message_data(message_id=20, channel_id=200)

        store.save(msg1)
        store.save(msg2)

        assert store.get_last_message_id(100) == 10
        assert store.get_last_message_id(200) == 20

    def test_database_file_created(self, tmp_path):
        """Файл БД создаётся при инициализации."""
        db_path = str(tmp_path / "test.db")
        store = MessageStore(db_path)
        store.close()

        assert Path(db_path).exists()

    def test_database_schema(self, store):
        """Таблица messages имеет правильную схему."""
        cursor = store._conn.execute(
            "PRAGMA table_info(messages)"
        )
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "message_id" in columns
        assert "channel_id" in columns
        assert "channel_name" in columns
        assert "text" in columns
        assert "link" in columns
        assert "timestamp" in columns
        assert "date" in columns


# =============================================================================
# ТЕСТЫ: WebhookClient
# =============================================================================

class TestWebhookClient:

    @pytest.mark.asyncio
    async def test_webhook_success(self):
        """Успешная отправка вебхука (200)."""
        msg = make_message_data()

        async with WebhookClient(
            url="http://localhost:8000/webhook/post",
            retries=1,
            retry_delay=0,
        ) as client:
            # Мокаем _try_send напрямую — это надёжнее
            client._try_send = AsyncMock(return_value={
                "status": "analyzed",
                "requires_response": True,
                "category": "ЖКХ",
                "urgency": "high",
            })
            result = await client.send(msg)

        assert result is not None
        assert result["status"] == "analyzed"

    @pytest.mark.asyncio
    async def test_webhook_rate_limit(self):
        """Rate limit (429) — возврат None без retry."""
        msg = make_message_data()

        async with WebhookClient(
            url="http://localhost:8000/webhook/post",
            retries=1,
            retry_delay=0,
        ) as client:
            client._try_send = AsyncMock(return_value=None)  # 429 → None
            result = await client.send(msg)

        assert result is None

    @pytest.mark.asyncio
    async def test_webhook_5xx_retries(self):
        """5xx ошибки — retry до лимита, потом None."""
        msg = make_message_data()
        call_count = 0

        async with WebhookClient(
            url="http://localhost:8000/webhook/post",
            retries=2,
            retry_delay=0,
        ) as client:
            async def fail_5xx(payload, attempt):
                nonlocal call_count
                call_count += 1
                return ...  # sentinel: нужно ретраить

            client._try_send = fail_5xx
            result = await client.send(msg)

            # retries=2 → _try_send вызван 2 раза
            assert call_count == 2
            assert result is None  # fail-safe → None

    @pytest.mark.asyncio
    async def test_webhook_4xx_no_retry(self):
        """4xx ошибки — без retry, один вызов."""
        msg = make_message_data()
        call_count = 0

        async with WebhookClient(
            url="http://localhost:8000/webhook/post",
            retries=3,
            retry_delay=0,
        ) as client:
            async def fail_4xx(payload, attempt):
                nonlocal call_count
                call_count += 1
                return None  # 4xx → не ретраим

            client._try_send = fail_4xx
            result = await client.send(msg)

            # 4xx — один вызов
            assert call_count == 1
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_timeout_retry(self):
        """Таймаут — retry до лимита."""
        msg = make_message_data()
        call_count = 0

        async with WebhookClient(
            url="http://localhost:8000/webhook/post",
            retries=2,
            retry_delay=0,
        ) as client:
            async def fail_timeout(payload, attempt):
                nonlocal call_count
                call_count += 1
                return ...  # sentinel: нужно ретраить

            client._try_send = fail_timeout
            result = await client.send(msg)

            # retries=2 → 2 вызова
            assert call_count == 2
            assert result is None

    @pytest.mark.asyncio
    async def test_webhook_fail_safe(self):
        """Fail-safe: при всех ошибках возврат None, не exception."""
        msg = make_message_data()

        async with WebhookClient(
            url="http://localhost:8000/webhook/post",
            retries=1,
            retry_delay=0,
            fail_safe=True,
        ) as client:
            async def fail_conn(payload, attempt):
                return ...  # conn error → retry → eventually None

            client._try_send = fail_conn
            result = await client.send(msg)

            # Fail-safe: None, а не exception
            assert result is None


# =============================================================================
# ТЕСТЫ: Вспомогательные функции
# =============================================================================

class TestHelperFunctions:

    def test_build_message_link(self):
        """Формирование ссылки на сообщение."""
        link = _build_message_link(chat_id=100, message_id=5)
        assert link == "https://max.me/c/100/5"

    def test_build_message_link_negative_ids(self):
        """Ссылка с отрицательными ID (MAX использует отрицательные chat_id)."""
        link = _build_message_link(chat_id=-71887474716883, message_id=123)
        assert link == "https://max.me/c/-71887474716883/123"


# =============================================================================
# ТЕСТЫ: Интеграция MessageStore + WebhookClient
# =============================================================================

class TestIntegration:

    def test_store_and_retrieve(self, store):
        """Полный цикл: сохранить → извлечь из БД."""
        msg = make_message_data(message_id=42, channel_id=100, text="Жалоба на воду")
        store.save(msg)

        cursor = store._conn.execute(
            "SELECT * FROM messages WHERE message_id = 42"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[4] == "Жалоба на воду"  # text column

    def test_unique_constraint(self, store):
        """UNIQUE(message_id, channel_id) предотвращает дубликаты."""
        msg1 = make_message_data(message_id=1, channel_id=100)
        msg2 = make_message_data(message_id=1, channel_id=100)

        store.save(msg1)
        store.save(msg2)

        count = store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 1

    def test_different_message_ids_same_channel(self, store):
        """Разные message_id в одном канале — разные записи."""
        msg1 = make_message_data(message_id=1, channel_id=100)
        msg2 = make_message_data(message_id=2, channel_id=100)

        store.save(msg1)
        store.save(msg2)

        count = store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 2

    def test_same_message_id_different_channel(self, store):
        """Одинаковый message_id в разных каналах — разные записи."""
        msg1 = make_message_data(message_id=1, channel_id=100)
        msg2 = make_message_data(message_id=1, channel_id=200)

        store.save(msg1)
        store.save(msg2)

        count = store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 2
