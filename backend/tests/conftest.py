import pytest

from kg_assistant.core.config import Settings


@pytest.fixture
def settings():
    return Settings(_env_file=None, neo4j_password="test-only-password")
