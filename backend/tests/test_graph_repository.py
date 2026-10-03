from unittest.mock import AsyncMock, MagicMock

import pytest
from graph_fixtures import sample_extraction

from kg_assistant.db.repositories.knowledge_graph import KnowledgeGraphRepository
from kg_assistant.ingestion.normalization import normalize_extraction
from kg_assistant.models.documents import Chunk


async def test_queries_use_configured_types_and_parameterized_values(settings):
    connection = MagicMock()
    repository = KnowledgeGraphRepository(
        connection, 30, settings.entity_types, settings.relationship_types, 120
    )
    normalized = normalize_extraction(sample_extraction())
    normalized.entities[0].name = "' }) CREATE (:Unexpected) //"
    chunk = Chunk(id="c", document_id="doc", text="text", chunk_index=0)
    tx = AsyncMock()
    result = AsyncMock()
    tx.run.return_value = result
    result.single.side_effect = [
        {"id": "doc"},
        {"count": 4},
        {"count": 1},
        {"count": 1},
        {"count": 1},
        {"id": "c"},
    ]
    relationships = [
        {**r.model_dump(), "id": str(i)} for i, r in enumerate(normalized.relationships)
    ]
    await repository._save_transaction(
        tx, chunk, [e.model_dump() for e in normalized.entities], relationships, 1, "run", "model"
    )
    calls = tx.run.call_args_list
    assert normalized.entities[0].name not in calls[1].args[0]
    assert calls[1].kwargs["entities"][0]["name"] == normalized.entities[0].name
    assert [":MANAGES ", ":USES ", ":HOSTED_ON "] == [
        next(token for token in [":MANAGES ", ":USES ", ":HOSTED_ON "] if token in call.args[0])
        for call in calls[2:5]
    ]


async def test_repository_rejects_unconfigured_relationship_before_database(settings):
    connection = MagicMock()
    repo = KnowledgeGraphRepository(
        connection, 30, settings.entity_types, settings.relationship_types, 120
    )
    normalized = normalize_extraction(sample_extraction())
    normalized.relationships[0].type = "USES]->(n) DELETE n //"
    with pytest.raises(ValueError):
        await repo.save_chunk(
            Chunk(id="c", document_id="d", text="x", chunk_index=0), normalized, 1, "run", "model"
        )
    connection.driver.session.assert_not_called()
