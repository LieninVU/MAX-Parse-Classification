"""
Тесты для AI-сервера (FastAPI) — endpoints, база данных, Pydantic-модели.
Тестирование ActionableStore (unit) + endpoints через прямой вызов store.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

# Импортируем модели и хранилище напрямую (без запуска сервера)
from analytics_server import (
    ActionableStore,
    AIAnalysis,
    PostWebhook,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture()
def test_db_path(tmp_path):
    """Временная база данных для тестов."""
    return str(tmp_path / "test_analytics.db")


@pytest.fixture()
def store(test_db_path):
    """Хранилище инцидентов с чистой БД."""
    s = ActionableStore(test_db_path)
    yield s
    s.close()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def make_post_webhook(text="Тестовый пост", message_id=1, channel_id=100):
    """Создать объект PostWebhook для тестов."""
    return PostWebhook(
        message_id=message_id,
        channel_id=channel_id,
        channel_name="Test Channel",
        text=text,
        link=f"https://max.me/c/{channel_id}/{message_id}",
        timestamp=int(datetime.now().timestamp()),
        date=datetime.now().isoformat(),
    )


def make_ai_analysis(requires_response=True, urgency="high", category="ЖКХ"):
    """Создать объект AIAnalysis для тестов."""
    return AIAnalysis(
        requires_response=requires_response,
        category=category,
        urgency=urgency,
        reason="Тестовое обоснование",
        draft_reply_thesis="Тестовый тезис ответа",
    )


# =============================================================================
# РАЗДЕЛ 1: Тесты ActionableStore (unit)
# =============================================================================

class TestActionableStore:

    def test_save_and_fetch(self, store):
        """Сохранение и получение одного инцидента."""
        post = make_post_webhook()
        analysis = make_ai_analysis()
        raw = json.dumps({"test": True})

        store.save(post, analysis, raw)

        posts = store.fetch()
        assert len(posts) == 1
        assert posts[0]["message_id"] == post.message_id
        assert posts[0]["category"] == "ЖКХ"
        assert posts[0]["urgency"] == "high"
        assert posts[0]["status"] == "new"

    def test_save_duplicate_ignored(self, store):
        """Дедупликация: повторная вставка игнорируется."""
        post = make_post_webhook()
        analysis = make_ai_analysis()

        store.save(post, analysis, json.dumps({}))
        store.save(post, analysis, json.dumps({}))

        posts = store.fetch()
        assert len(posts) == 1

    def test_fetch_filter_by_status(self, store):
        """Фильтрация инцидентов по статусу."""
        post1 = make_post_webhook(message_id=1)
        post2 = make_post_webhook(message_id=2)
        analysis = make_ai_analysis()

        store.save(post1, analysis, json.dumps({}))
        store.save(post2, analysis, json.dumps({}))
        store.update_status(post2.message_id, "resolved")

        new_posts = store.fetch(status="new")
        assert len(new_posts) == 1

        resolved_posts = store.fetch(status="resolved")
        assert len(resolved_posts) == 1

    def test_fetch_filter_by_urgency(self, store):
        """Фильтрация инцидентов по срочности."""
        post1 = make_post_webhook(message_id=1)
        post2 = make_post_webhook(message_id=2)

        store.save(post1, make_ai_analysis(urgency="high"), json.dumps({}))
        store.save(post2, make_ai_analysis(urgency="low"), json.dumps({}))

        high_posts = store.fetch(urgency="high")
        assert len(high_posts) == 1
        assert high_posts[0]["urgency"] == "high"

    def test_fetch_sorted_by_urgency(self, store):
        """Сортировка: high → medium → low."""
        post1 = make_post_webhook(message_id=1)
        post2 = make_post_webhook(message_id=2)
        post3 = make_post_webhook(message_id=3)

        store.save(post1, make_ai_analysis(urgency="low"), json.dumps({}))
        store.save(post2, make_ai_analysis(urgency="high"), json.dumps({}))
        store.save(post3, make_ai_analysis(urgency="medium"), json.dumps({}))

        posts = store.fetch()
        urgencies = [p["urgency"] for p in posts]
        assert urgencies == ["high", "medium", "low"]

    def test_fetch_limit(self, store):
        """Лимит возвращаемых записей."""
        for i in range(10):
            store.save(make_post_webhook(message_id=i), make_ai_analysis(), json.dumps({}))

        posts = store.fetch(limit=3)
        assert len(posts) == 3

    def test_update_status(self, store):
        """Обновление статуса инцидента."""
        post = make_post_webhook()
        store.save(post, make_ai_analysis(), json.dumps({}))

        affected = store.update_status(post.message_id, "in_progress")
        assert affected == 1

        fetched = store.fetch_one(post.message_id)
        assert fetched["status"] == "in_progress"

    def test_update_status_not_found(self, store):
        """Обновление статуса несуществующего инцидента."""
        affected = store.update_status(99999, "resolved")
        assert affected == 0

    def test_fetch_one_not_found(self, store):
        """Получение несуществующего инцидента."""
        result = store.fetch_one(99999)
        assert result is None

    def test_get_stats(self, store):
        """Статистика по инцидентам."""
        post1 = make_post_webhook(message_id=1)
        post2 = make_post_webhook(message_id=2)
        post3 = make_post_webhook(message_id=3)

        store.save(post1, make_ai_analysis(urgency="high", category="ЖКХ"), json.dumps({}))
        store.save(post2, make_ai_analysis(urgency="low", category="Дороги"), json.dumps({}))
        store.save(post3, make_ai_analysis(urgency="high", category="ЖКХ"), json.dumps({}))

        stats = store.get_stats()
        assert stats["total_actionable"] == 3
        assert stats["by_urgency"]["high"] == 2
        assert stats["by_urgency"]["low"] == 1
        assert stats["by_category"]["ЖКХ"] == 2
        assert stats["by_category"]["Дороги"] == 1

    def test_fetch_with_limit_param(self, store):
        """Query limit корректно ограничивает результат."""
        for i in range(5):
            store.save(make_post_webhook(message_id=i), make_ai_analysis(), json.dumps({}))

        posts = store.fetch(limit=2)
        assert len(posts) == 2


# =============================================================================
# РАЗДЕЛ 2: Тесты Pydantic-моделей
# =============================================================================

class TestPydanticModels:

    def test_post_webhook_valid(self):
        """Валидация PostWebhook с полными данными."""
        data = {
            "message_id": 1,
            "channel_id": 100,
            "channel_name": "Test",
            "text": "Hello",
            "link": "https://example.com",
            "timestamp": 1234567890,
            "date": "2024-01-01T00:00:00",
        }
        post = PostWebhook(**data)
        assert post.message_id == 1
        assert post.text == "Hello"

    def test_post_webhook_optional_fields(self):
        """PostWebhook допускает None для text и link."""
        data = {
            "message_id": 1,
            "channel_id": 100,
            "channel_name": "Test",
            "text": None,
            "link": None,
            "timestamp": 1234567890,
            "date": "2024-01-01T00:00:00",
        }
        post = PostWebhook(**data)
        assert post.text is None
        assert post.link is None

    def test_ai_analysis_valid(self):
        """Валидация AIAnalysis."""
        data = {
            "requires_response": True,
            "category": "ЖКХ",
            "urgency": "high",
            "reason": "No water in building",
            "draft_reply_thesis": "We will fix it",
        }
        analysis = AIAnalysis(**data)
        assert analysis.requires_response is True

    def test_ai_analysis_all_fields(self):
        """AIAnalysis — все поля обязательны."""
        analysis = AIAnalysis(
            requires_response=False,
            category="Другое",
            urgency="low",
            reason="No reason",
            draft_reply_thesis="No reply",
        )
        assert analysis.requires_response is False
        assert analysis.category == "Другое"
        assert analysis.urgency == "low"

    def test_post_webhook_required_fields(self):
        """PostWebhook — обязательные поля."""
        with pytest.raises(Exception):
            PostWebhook(
                channel_id=100,
                channel_name="Test",
                timestamp=123,
                date="2024-01-01",
            )


# =============================================================================
# РАЗДЕЛ 3: Тесты бизнес-логики (сквозные сценарии через Store)
# =============================================================================

class TestBusinessLogic:

    def test_full_incident_lifecycle(self, store):
        """Полный цикл: создание → просмотр → обновление статуса → статистика."""
        # 1. Создание инцидента
        post = make_post_webhook(text="В доме прорвало трубу", message_id=100)
        analysis = make_ai_analysis(urgency="high", category="ЖКХ")
        store.save(post, analysis, json.dumps({"raw": True}))

        # 2. Проверка: инцидент в базе
        posts = store.fetch()
        assert len(posts) == 1
        assert posts[0]["text"] == "В доме прорвало трубу"
        assert posts[0]["status"] == "new"

        # 3. Обновление статуса
        store.update_status(post.message_id, "in_progress")
        updated = store.fetch_one(post.message_id)
        assert updated["status"] == "in_progress"

        # 4. Статистика
        stats = store.get_stats()
        assert stats["total_actionable"] == 1
        assert stats["by_status"]["in_progress"] == 1

    def test_multiple_incidents_filtering(self, store):
        """Несколько инцидентов с фильтрацией по категории."""
        categories = ["ЖКХ", "Дороги", "ЧП", "ЖКХ", "Экология"]
        for i, cat in enumerate(categories):
            post = make_post_webhook(message_id=i)
            store.save(post, make_ai_analysis(category=cat), json.dumps({}))

        # Фильтр по ЖКХ
        zkh = store.fetch()  # без фильтра — все
        zkh_filtered = [p for p in zkh if p["category"] == "ЖКХ"]
        assert len(zkh_filtered) == 2

        # Фильтр по high urgency
        high = store.fetch(urgency="high")
        assert len(high) == 5  # все high по умолчанию

    def test_status_values(self, store):
        """Все допустимые статусы."""
        post = make_post_webhook()
        store.save(post, make_ai_analysis(), json.dumps({}))

        for status in ["new", "in_progress", "resolved", "ignored"]:
            affected = store.update_status(post.message_id, status)
            assert affected == 1
            fetched = store.fetch_one(post.message_id)
            assert fetched["status"] == status

    def test_empty_text_post(self, store):
        """Инцидент без текста сохраняется."""
        post = make_post_webhook(text=None)
        store.save(post, make_ai_analysis(), json.dumps({}))

        posts = store.fetch()
        assert len(posts) == 1
        assert posts[0]["text"] is None

    def test_stats_empty_database(self, store):
        """Статистика на пустой базе."""
        stats = store.get_stats()
        assert stats["total_actionable"] == 0
        assert stats["by_urgency"] == {}
        assert stats["by_status"] == {}
        assert stats["by_category"] == {}
