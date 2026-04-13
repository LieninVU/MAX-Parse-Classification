"""
Тесты AI-сервера через FastAPI TestClient (эндпоинты + LLMClient).
Тестирование полного цикла: webhook → анализ → БД → REST API.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Мокаем pymax для импорта
import sys
from unittest.mock import MagicMock
sys.modules.setdefault("pymax", MagicMock())

from analytics_server import (
    AIAnalysis,
    LLMClient,
    PostWebhook,
    app,
    lifespan,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture()
def test_db_path(tmp_path):
    """Временная база данных для тестов."""
    return str(tmp_path / "test_analytics_endpoints.db")


@pytest.fixture()
def client(test_db_path, monkeypatch):
    """TestClient с чистой БД и замоканным LLM."""
    # Подменяем DB_PATH перед инициализацией
    monkeypatch.setattr("analytics_server.CFG_DB_PATH", test_db_path)
    # Мокаем LLM — чтобы не обращаться к OpenRouter
    monkeypatch.setattr("analytics_server.CFG_OPENROUTER_KEY", "sk-or-fake-key")

    with TestClient(app) as c:
        yield c


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
    """Создать объект AIAnalysis."""
    return AIAnalysis(
        requires_response=requires_response,
        category=category,
        urgency=urgency,
        reason="Тестовое обоснование",
        draft_reply_thesis="Тестовый тезис ответа",
    )


# =============================================================================
# РАЗДЕЛ 1: Endpoints (POST /webhook/post)
# =============================================================================

class TestWebhookEndpoint:

    def test_receive_post_empty_text(self, client):
        """Пост без текста пропускается."""
        response = client.post("/webhook/post", json={
            "message_id": 1,
            "channel_id": 100,
            "channel_name": "Test",
            "text": None,
            "link": None,
            "timestamp": 1234567890,
            "date": "2024-01-01T00:00:00",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert "no text" in data["reason"]

    def test_receive_post_whitespace_only(self, client):
        """Пост с пробелами вместо текста пропускается."""
        response = client.post("/webhook/post", json={
            "message_id": 2,
            "channel_id": 100,
            "channel_name": "Test",
            "text": "   \n\t  ",
            "link": None,
            "timestamp": 1234567890,
            "date": "2024-01-01T00:00:00",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"


# =============================================================================
# РАЗДЕЛ 2: Endpoints (GET /actionable, PATCH /status)
# =============================================================================

class TestActionableEndpoints:

    def test_get_actionable_empty(self, client):
        """Получение списка инцидентов из пустой БД."""
        response = client.get("/actionable")
        assert response.status_code == 200
        assert response.json() == []

    def test_update_status_invalid(self, client):
        """Обновление статуса с невалидным значением."""
        response = client.patch("/actionable/1/status", params={"status": "invalid_status"})
        assert response.status_code == 400

    def test_update_status_not_found(self, client):
        """Обновление статуса несуществующего инцидента."""
        response = client.patch("/actionable/99999/status", params={"status": "resolved"})
        assert response.status_code == 404

    def test_get_post_not_found(self, client):
        """Получение несуществующего инцидента."""
        response = client.get("/actionable/99999")
        assert response.status_code == 404


# =============================================================================
# РАЗДЕЛ 3: Endpoints (GET /stats, GET /health)
# =============================================================================

class TestSystemEndpoints:

    def test_health_check(self, client):
        """Health check возвращает ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_stats_empty(self, client):
        """Статистика на пустой базе."""
        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_actionable"] == 0
        assert data["by_urgency"] == {}
        assert data["by_status"] == {}
        assert data["by_category"] == {}


# =============================================================================
# РАЗДЕЛ 4: LLMClient (unit)
# =============================================================================

class TestLLMClient:

    def test_parse_response_valid_json(self):
        """Парсинг валидного JSON ответа от LLM."""
        content = json.dumps({
            "requires_response": True,
            "category": "ЖКХ",
            "urgency": "high",
            "reason": "No water",
            "draft_reply_thesis": "We will fix",
        })
        analysis = LLMClient._parse_response(content)
        assert analysis.requires_response is True
        assert analysis.category == "ЖКХ"
        assert analysis.urgency == "high"

    def test_parse_response_with_markdown_wrapper(self):
        """Парсинг JSON с markdown-обёрткой ```json ... ```."""
        content = '```json\n{"requires_response": false, "category": "Другое", "urgency": "low", "reason": "News", "draft_reply_thesis": "No reply"}\n```'
        analysis = LLMClient._parse_response(content)
        assert analysis.requires_response is False
        assert analysis.category == "Другое"

    def test_parse_response_urgency_normalization(self):
        """Нормализация urgency к medium при невалидном значении."""
        content = json.dumps({
            "requires_response": True,
            "category": "ЖКХ",
            "urgency": "CRITICAL",  # невалидное
            "reason": "Test",
            "draft_reply_thesis": "Test",
        })
        analysis = LLMClient._parse_response(content)
        assert analysis.urgency == "medium"

    def test_parse_response_missing_keys(self):
        """Ошибка при отсутствующих ключах."""
        content = json.dumps({"requires_response": True})
        with pytest.raises(ValueError, match="missing keys"):
            LLMClient._parse_response(content)

    def test_parse_response_invalid_json(self):
        """Ошибка при невалидном JSON."""
        content = "This is not JSON at all"
        with pytest.raises(ValueError, match="Invalid JSON"):
            LLMClient._parse_response(content)


# =============================================================================
# РАЗДЕЛ 5: Сквозные сценарии (Store + Endpoints)
# =============================================================================

class TestEndToEndScenarios:

    def test_full_post_lifecycle_via_store(self, tmp_path):
        """Полный цикл: save → fetch → update status → stats."""
        from analytics_server import ActionableStore

        db_path = str(tmp_path / "lifecycle.db")
        store = ActionableStore(db_path)

        # 1. Сохранение инцидента
        post = make_post_webhook(text="Прорвало трубу в подвале", message_id=100)
        analysis = make_ai_analysis(urgency="high", category="ЖКХ")
        store.save(post, analysis, json.dumps({}))

        # 2. Получение
        posts = store.fetch()
        assert len(posts) == 1
        assert posts[0]["text"] == "Прорвало трубу в подвале"
        assert posts[0]["status"] == "new"

        # 3. Обновление статуса
        affected = store.update_status(post.message_id, "in_progress")
        assert affected == 1

        # 4. Проверка статуса
        updated = store.fetch_one(post.message_id)
        assert updated["status"] == "in_progress"

        # 5. Статистика
        stats = store.get_stats()
        assert stats["total_actionable"] == 1
        assert stats["by_status"]["in_progress"] == 1

        store.close()

    def test_multiple_categories_and_filtering(self, tmp_path):
        """Фильтрация инцидентов по разным категориям."""
        from analytics_server import ActionableStore

        db_path = str(tmp_path / "categories.db")
        store = ActionableStore(db_path)

        categories_data = [
            ("Прорвало трубу", "ЖКХ", "high"),
            ("Яма на дороге", "Дороги", "medium"),
            ("Пожар на складе", "ЧП", "high"),
            ("Мусор во дворе", "Благоустройство", "low"),
        ]

        for i, (text, cat, urg) in enumerate(categories_data):
            post = make_post_webhook(text=text, message_id=i)
            analysis = make_ai_analysis(category=cat, urgency=urg)
            store.save(post, analysis, json.dumps({}))

        # Все инциденты
        all_posts = store.fetch()
        assert len(all_posts) == 4

        # Сортировка: high сначала
        assert all_posts[0]["urgency"] == "high"
        assert all_posts[1]["urgency"] == "high"

        # Фильтрация по status
        new_posts = store.fetch(status="new")
        assert len(new_posts) == 4

        store.close()
