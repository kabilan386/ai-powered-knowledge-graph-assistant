from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from kg_assistant.db.repositories.documents import STORE_DOCUMENT, DocumentRepository
from kg_assistant.models.documents import Chunk, Document


async def test_parameterized_write_uses_single_managed_transaction(settings):
    connection = MagicMock()
    connection.settings = settings
    session = AsyncMock()
    connection.driver.session.return_value.__aenter__.return_value = session
    doc = Document(id="doc", filename="a.txt", file_type="txt", created_at=datetime.now(UTC))
    malicious_text = "' }) CREATE (:Unexpected) //"
    chunks = [Chunk(id="chunk", document_id=doc.id, text=malicious_text, chunk_index=0)]
    repository = DocumentRepository(connection, 5)
    await repository.save(doc, chunks)
    session.execute_write.assert_awaited_once()
    callback, doc_data, chunk_data = session.execute_write.call_args.args
    tx = AsyncMock()
    result = AsyncMock()
    result.single.return_value = {"chunk_count": 1}
    tx.run.return_value = result
    await callback(tx, doc_data, chunk_data)
    query = tx.run.call_args.args[0]
    assert query == STORE_DOCUMENT
    assert malicious_text not in query
    assert tx.run.call_args.kwargs["chunks"][0]["text"] == malicious_text
    assert session.run.await_count == 2  # Constraints are idempotent DDL, outside the data write.


async def test_mismatched_document_is_rejected(settings):
    connection = MagicMock()
    doc = Document(id="doc", filename="a.txt", file_type="txt", created_at=datetime.now(UTC))
    chunk = Chunk(id="c", document_id="different", text="text", chunk_index=0)
    with pytest.raises(ValueError):
        await DocumentRepository(connection, 5).save(doc, [chunk])
    connection.driver.session.assert_not_called()
