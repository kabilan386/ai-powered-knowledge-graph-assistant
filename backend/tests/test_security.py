from io import BytesIO
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import UploadFile

from kg_assistant.core.body_limit import RequestBodyLimitMiddleware
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.main import create_app
from kg_assistant.services.documents import DocumentService


@pytest.mark.parametrize("declared", ["99999999", "-1", "invalid"])
async def test_request_size_rejection_before_parsing(settings, declared):
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/documents/upload",
            content=b"x",
            headers={
                "Content-Length": declared,
                "Origin": "http://localhost:3000",
            },
        )
    assert response.status_code == (413 if declared == "99999999" else 400)
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "X-Request-ID" in response.headers


@pytest.mark.parametrize(
    "path,limit", [("/api/documents/upload", 8 + 65536), ("/api/graphrag/ask", 128 * 1024)]
)
async def test_streamed_body_limit_without_content_length(path, limit):
    app = AsyncMock()
    guard = RequestBodyLimitMiddleware(app, max_file_size=8)
    receive = AsyncMock(
        side_effect=[
            {"type": "http.request", "body": b"x" * limit, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )
    send = AsyncMock()
    await guard({"type": "http", "method": "POST", "path": path, "headers": []}, receive, send)
    app.assert_not_called()
    assert send.call_args_list[0].args[0]["status"] == 413


async def test_accepted_body_replayed_unchanged():
    seen = []

    async def downstream(scope, receive, send):
        seen.append(await receive())

    guard = RequestBodyLimitMiddleware(downstream, max_file_size=8)
    receive = AsyncMock(
        side_effect=[
            {"type": "http.request", "body": b"ab", "more_body": True},
            {"type": "http.request", "body": b"cd", "more_body": False},
        ]
    )
    await guard(
        {"type": "http", "method": "POST", "path": "/api/graphrag/ask", "headers": []},
        receive,
        AsyncMock(),
    )
    assert seen == [{"type": "http.request", "body": b"abcd", "more_body": False}]


@pytest.mark.parametrize("name", ["bad\x00.txt", "bad\n.txt", "bad\x7f.txt"])
async def test_filename_controls_rejected_and_file_closed(settings, name):
    service = DocumentService(settings, AsyncMock(), AsyncMock(), AsyncMock())
    file = UploadFile(filename=name, file=BytesIO(b"sample"))
    with pytest.raises(IngestionError) as error:
        await service.upload(file)
    assert error.value.code == "invalid_filename" and file.file.closed
    service.repository.save.assert_not_called()
