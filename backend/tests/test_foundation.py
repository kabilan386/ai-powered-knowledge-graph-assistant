import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from pydantic import ValidationError

from kg_assistant.api.dependencies import get_neo4j
from kg_assistant.core.config import Settings
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.main import create_app


def test_env_config_and_secret_redaction(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "test-env-secret")
    monkeypatch.setenv("NEO4J_DATABASE", "testdb")
    config = Settings(_env_file=None)
    assert config.neo4j_database == "testdb"
    assert "test-env-secret" not in repr(config)


@pytest.mark.parametrize("password", ["", "  ", "replace-with-a-local-password"])
def test_invalid_password(password):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password=password)


def test_missing_password(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("uri", ["http://localhost:7687", "bolt://", "bolt://user:secret@host"])
def test_invalid_uri(uri):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password="test", neo4j_uri=uri)


def test_health_and_lifespan(settings):
    driver = MagicMock()
    driver.close = AsyncMock()
    connection = MagicMock()
    connection.healthy = AsyncMock(return_value=True)
    app = create_app(settings)
    app.dependency_overrides[get_neo4j] = lambda: connection
    with patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver):
        with TestClient(app) as client:
            live = client.get("/health/live")
            assert live.status_code == 200
            assert live.json()["status"] == "ok"
            assert len(live.headers["X-Request-ID"]) == 32
            connection.healthy.assert_not_called()
            ready = client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ok", "neo4j": "up"}
            connection.healthy.return_value = False
            assert client.get("/health/ready").status_code == 503
            assert client.get("/health/live").status_code == 200
        driver.close.assert_awaited_once()


def test_unexpected_errors_are_sanitized(settings):
    app = create_app(settings)
    connection = MagicMock()
    connection.healthy = AsyncMock(side_effect=RuntimeError("sensitive details"))
    app.dependency_overrides[get_neo4j] = lambda: connection
    driver = MagicMock()
    driver.close = AsyncMock()
    with patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver):
        with TestClient(app) as client:
            response = client.get("/health/ready")
            assert response.status_code == 500
            assert "sensitive details" not in response.text
            assert "X-Request-ID" in response.headers


async def test_manager_success_and_cleanup(settings):
    driver = MagicMock()
    driver.close = AsyncMock()
    session = AsyncMock()
    result = AsyncMock()
    result.single.return_value = {"ok": 1}
    session.run.return_value = result
    driver.session.return_value.__aenter__.return_value = session
    manager = Neo4jConnectionManager(settings)
    with patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver) as factory:
        await manager.start()
        await manager.start()
        factory.assert_called_once()
        assert await manager.healthy()
        driver.session.assert_called_once_with(database=settings.neo4j_database)
        await manager.close()
        await manager.close()
        driver.close.assert_awaited_once()
        with pytest.raises(RuntimeError):
            _ = manager.driver


@pytest.mark.parametrize("failure", [ServiceUnavailable("private"), TimeoutError()])
async def test_manager_failure(settings, failure):
    manager = Neo4jConnectionManager(settings)
    driver = MagicMock()
    driver.session.side_effect = failure
    manager._driver = driver
    assert await manager.healthy() is False


async def test_manager_timeout(settings):
    settings.neo4j_health_timeout = 0.01
    manager = Neo4jConnectionManager(settings)
    driver = MagicMock()
    session = AsyncMock()

    async def slow(*args):
        await asyncio.sleep(1)

    session.run.side_effect = slow
    driver.session.return_value.__aenter__.return_value = session
    manager._driver = driver
    assert await manager.healthy() is False
