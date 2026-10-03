from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from document_fixtures import docx_bytes, pdf_bytes
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from kg_assistant.api.dependencies import get_document_repository
from kg_assistant.main import create_app


@pytest.fixture
def upload_client(settings):
    settings.chunk_size = 20
    settings.chunk_overlap = 5
    repository = AsyncMock()
    app = create_app(settings)
    app.dependency_overrides[get_document_repository] = lambda: repository
    driver = MagicMock()
    driver.close = AsyncMock()
    with patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver):
        with TestClient(app) as client:
            yield client, repository


@pytest.mark.parametrize(
    "filename,content,kind",
    [
        ("note.TXT", b"A short note", "txt"),
        ("sample.pdf", pdf_bytes(["First page", "Second page"]), "pdf"),
        ("sample.docx", docx_bytes(), "docx"),
    ],
)
def test_upload_success(upload_client, filename, content, kind):
    client, repository = upload_client
    response = client.post("/api/documents/upload", files={"file": (filename, content)})
    assert response.status_code == 201
    body = response.json()
    document, chunks = repository.save.call_args.args
    assert body["document"]["id"] == document.id
    assert body["document"]["filename"] == filename
    assert body["document"]["file_type"] == kind
    assert body["document"]["created_at"].endswith("Z")
    assert body["chunk_count"] == len(chunks)
    assert all(c.document_id == document.id for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    if kind == "pdf":
        assert [c.page_number for c in chunks] == [1, 2]


@pytest.mark.parametrize(
    "filename,content,status,code",
    [
        ("file.exe", b"hello", 415, "unsupported_file"),
        ("empty.txt", b"", 400, "empty_file"),
        ("space.txt", b" \n", 422, "no_text"),
        ("fake.pdf", b"broken", 422, "invalid_document"),
    ],
)
def test_upload_rejections(upload_client, filename, content, status, code):
    client, repository = upload_client
    response = client.post("/api/documents/upload", files={"file": (filename, content)})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    repository.save.assert_not_awaited()


def test_file_size_limit_and_exact_limit(upload_client):
    client, repository = upload_client
    client.app.state.settings.max_file_size = 4
    assert (
        client.post("/api/documents/upload", files={"file": ("n.txt", b"1234")}).status_code == 201
    )
    repository.save.reset_mock()
    response = client.post("/api/documents/upload", files={"file": ("n.txt", b"12345")})
    assert response.status_code == 413
    repository.save.assert_not_awaited()


def test_missing_file(upload_client):
    client, repository = upload_client
    assert client.post("/api/documents/upload").status_code == 422
    repository.save.assert_not_awaited()


def test_database_outage(upload_client):
    client, repository = upload_client
    repository.save.side_effect = ServiceUnavailable("private-database-password")
    response = client.post("/api/documents/upload", files={"file": ("n.txt", b"hello")})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "private-database-password" not in response.text


def test_filename_basename(upload_client):
    client, repository = upload_client
    response = client.post("/api/documents/upload", files={"file": ("../../notes.txt", b"hello")})
    assert response.status_code == 201
    assert response.json()["document"]["filename"] == "notes.txt"
