"""Scripted provider/database test doubles. Not a real embedding or LLM quality benchmark."""

import hashlib
import math
import re
from contextlib import asynccontextmanager

from kg_assistant.core.config import Settings
from kg_assistant.db.repositories.graph_retrieval import EVIDENCE, NEIGHBORS, RESOLVE
from kg_assistant.evaluation.models import ResolvedGroundTruth
from kg_assistant.evaluation.observations import ObservedQueryProvider
from kg_assistant.evaluation.repository import resolve_rows
from kg_assistant.evaluation.runner import EvaluationRuntime
from kg_assistant.ingestion.normalization import normalize_name
from kg_assistant.models.graph_retrieval import GraphEntity, QueryEntity, QueryExtraction
from kg_assistant.models.graphrag import GroundedAnswer, SourceChunk
from kg_assistant.models.retrieval import VectorSearchResult
from kg_assistant.retrieval.graph import GraphRetrievalService
from kg_assistant.retrieval.query_entities import QueryEntityExtractionService
from kg_assistant.retrieval.vector import VectorRetrievalService
from kg_assistant.services.embeddings import EmbeddingService

# Public fixture corpus. Answer rules below use these facts, never expected dataset answers.
FACTS = [
    (
        "01-platform-management.txt",
        "Platform Team manages Payment Service.",
        "Platform Team",
        "ORGANIZATION",
        "MANAGES",
        "Payment Service",
        "SERVICE",
    ),
    (
        "02-payment-cache.txt",
        "Payment Service uses Redis for caching.",
        "Payment Service",
        "SERVICE",
        "USES",
        "Redis",
        "TECHNOLOGY",
    ),
    (
        "03-redis-hosting.txt",
        "Redis is hosted on AWS ElastiCache.",
        "Redis",
        "TECHNOLOGY",
        "HOSTED_ON",
        "AWS ElastiCache",
        "CLOUD_SERVICE",
    ),
    (
        "04-customer-storage.txt",
        "Customer Service stores transactional data in PostgreSQL.",
        "Customer Service",
        "SERVICE",
        "USES",
        "PostgreSQL",
        "DATABASE",
    ),
    (
        "05-analytics-management.txt",
        "Analytics Team manages Analytics Service.",
        "Analytics Team",
        "ORGANIZATION",
        "MANAGES",
        "Analytics Service",
        "SERVICE",
    ),
    (
        "06-analytics-technology.txt",
        "Analytics Service uses Neo4j.",
        "Analytics Service",
        "SERVICE",
        "USES",
        "Neo4j",
        "TECHNOLOGY",
    ),
]


def fixture_chunks() -> list[SourceChunk]:
    return [
        SourceChunk(
            document_id=f"fixture-doc-{i}",
            chunk_id=f"fixture-chunk-{i}",
            filename=fact[0],
            chunk_index=0,
            text=fact[1],
        )
        for i, fact in enumerate(FACTS)
    ]


class FixtureEmbeddingProvider:
    """Deterministic hash bag of words with a few explicit demo aliases; no learned semantics."""

    async def embed_batch(self, texts):
        return [self.vector(text) for text in texts]

    @staticmethod
    def vector(text):
        text = (
            normalize_name(text).replace("application", "service").replace("solution", "technology")
        )
        stop = {
            "what",
            "which",
            "does",
            "is",
            "the",
            "by",
            "a",
            "of",
            "for",
            "to",
            "used",
            "use",
            "uses",
            "managed",
            "manages",
            "hosts",
            "hosted",
            "on",
            "technology",
        }
        vector = [0.0] * 64
        for word in re.findall(r"\w+", text):
            if word not in stop:
                vector[int.from_bytes(hashlib.sha256(word.encode()).digest()[:2]) % 64] += 1
        if not any(vector):
            vector[0] = 1
        return vector

    async def close(self):
        pass


class FixtureStore:
    def __init__(self):
        self.chunks = fixture_chunks()
        self.entities = {}
        self.edges = []
        for index, fact in enumerate(FACTS):
            nodes = []
            for name, kind in [(fact[2], fact[3]), (fact[5], fact[6])]:
                entity = GraphEntity(id=f"{kind}:{normalize_name(name)}", name=name, type=kind)
                self.entities[entity.id] = entity
                nodes.append(entity)
            self.edges.append((nodes[0].id, fact[4], nodes[1].id, index))

    async def ensure_index(self):
        pass

    async def search(self, vector, top_k):
        result = []
        for chunk in self.chunks:
            embedding = FixtureEmbeddingProvider.vector(chunk.text)
            cosine = sum(a * b for a, b in zip(vector, embedding, strict=True)) / (
                math.hypot(*vector) * math.hypot(*embedding)
            )
            result.append(
                VectorSearchResult(
                    **chunk.model_dump(exclude={"text_truncated"}),
                    score=min(1.0, max(0.0, (1 + cosine) / 2)),
                )
            )
        return sorted(result, key=lambda row: (-row.score, row.chunk_id))[:top_k]

    async def load_chunks(self, references):
        return [chunk for chunk in self.chunks if (chunk.document_id, chunk.chunk_id) in references]

    async def resolve_sources(self, selectors):
        if not selectors:
            return ResolvedGroundTruth(status="unannotated")
        rows = []
        for index, selector in enumerate(selectors):
            for chunk in self.chunks:
                if all(
                    value is None
                    or (value in chunk.text if key == "quote" else getattr(chunk, key) == value)
                    for key, value in selector.model_dump().items()
                ):
                    rows.append(
                        {
                            "selector_index": index,
                            "document_id": chunk.document_id,
                            "chunk_id": chunk.chunk_id,
                        }
                    )
        return resolve_rows(len(selectors), rows)

    async def audit(self, references):
        docs = {chunk.document_id for chunk in self.chunks}
        chunks = {chunk.chunk_id for chunk in self.chunks}
        pairs = {(chunk.document_id, chunk.chunk_id) for chunk in self.chunks}
        return [
            {
                "document_id": doc,
                "chunk_id": chunk,
                "document_exists": doc in docs,
                "chunk_exists": chunk in chunks,
                "linked": (doc, chunk) in pairs,
            }
            for doc, chunk in references
        ]


class FixtureRows:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row

        return iterate()


class FixtureTransaction:
    def __init__(self, store):
        self.store = store

    async def run(self, statement, **params):
        if statement == RESOLVE:
            rows = [
                entity.model_dump()
                for entity in self.store.entities.values()
                if normalize_name(entity.name) == params["name"]
                and (params["type"] is None or entity.type == params["type"])
            ]
        elif statement == NEIGHBORS:
            rows = []
            for source, kind, target, _ in self.store.edges:
                current = params["id"]
                if kind not in params["types"] or current not in {source, target}:
                    continue
                if (
                    params["direction"] == "outgoing"
                    and source != current
                    or params["direction"] == "incoming"
                    and target != current
                ):
                    continue
                other = self.store.entities[target if source == current else source]
                rows.append(
                    {
                        **other.model_dump(),
                        "relationship_type": kind,
                        "source_id": source,
                        "target_id": target,
                    }
                )
        elif statement == EVIDENCE:
            rows = []
            for source, kind, target, index in self.store.edges:
                if (source, kind, target) == (params["source"], params["type"], params["target"]):
                    chunk = self.store.chunks[index]
                    rows.append(
                        {
                            "relationship_id": f"fact-{index}",
                            "document_id": chunk.document_id,
                            "chunk_id": chunk.chunk_id,
                            "filename": chunk.filename,
                            "chunk_index": chunk.chunk_index,
                            "page_number": None,
                            "evidence_quote": chunk.text,
                        }
                    )
        else:
            raise AssertionError("Unexpected Cypher in fixture test double")
        return FixtureRows(rows[: params["limit"]])


class FixtureConnection:
    def __init__(self, store):
        self.store = store
        self.driver = self

    @asynccontextmanager
    async def session(self, **_kwargs):
        yield self

    async def execute_read(self, callback):
        return await callback(FixtureTransaction(self.store))


class FixtureQueryProvider:
    def __init__(self, store):
        self.store = store

    async def extract(self, question):
        text = normalize_name(question)
        entities = [
            QueryEntity(name=entity.name, type=entity.type)
            for entity in self.store.entities.values()
            if normalize_name(entity.name) in text
        ]
        hints = []
        if "managed" in text:
            hints.append("MANAGES")
        if "use" in text or "technology" in text:
            hints.append("USES")
        if "host" in text:
            hints.append("HOSTED_ON")
        return QueryExtraction(entities=entities, relationship_types=hints, direction="outgoing")


class FixtureAnswerProvider:
    async def generate(self, question, context):
        text = normalize_name(question)
        # Scripted fixture behavior grounded in supplied text; no access to gold annotations.
        if "cloud" in text and "host" in text:
            needed, answer = [0, 1, 2], "AWS ElastiCache"
        elif "platform team" in text and "technology" in text:
            needed, answer = [0, 1], "Redis"
        elif "platform team" in text and "service" in text:
            needed, answer = [0], "Payment Service"
        elif "payment" in text and ("use" in text or "caching" in text):
            needed, answer = [1], "Redis"
        elif "customer" in text:
            needed, answer = [3], "PostgreSQL"
        elif "analytics" in text and ("use" in text or "technology" in text):
            needed, answer = [5], "Neo4j"
        else:
            return GroundedAnswer(
                answer="No supporting information.", citations=[], insufficient_evidence=True
            )
        citations = []
        for index in needed:
            source = next(
                (item for item in context.text_evidence if FACTS[index][1] in item.excerpt), None
            )
            if source is None:
                return GroundedAnswer(
                    answer="Missing supporting facts.", citations=[], insufficient_evidence=True
                )
            citations.append(source.citation)
        citations = list(dict.fromkeys(citations))
        return GroundedAnswer(
            answer=answer + " " + " ".join(f"[{citation}]" for citation in citations),
            citations=citations,
            insufficient_evidence=False,
        )


def fixture_runtime(top_k=5) -> EvaluationRuntime:
    settings = Settings(
        _env_file=None,
        neo4j_password="fixture-only",
        embedding_enabled=True,
        embedding_model="fixture-hash-bag",
        embedding_dimensions=64,
        graph_retrieval_enabled=True,
        graphrag_enabled=True,
        openai_api_key="fixture-only-not-a-key",
        llm_model="fixture-rules",
        vector_top_k=top_k,
    )
    store = FixtureStore()
    vector = VectorRetrievalService(
        settings, store, EmbeddingService(FixtureEmbeddingProvider(), settings)
    )
    extractor = QueryEntityExtractionService(
        settings, ObservedQueryProvider(FixtureQueryProvider(store))
    )
    graph = GraphRetrievalService(settings, FixtureConnection(store), extractor)
    return EvaluationRuntime(settings, vector, graph, store, FixtureAnswerProvider(), store)
