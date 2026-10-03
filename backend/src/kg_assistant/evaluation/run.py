import argparse
import asyncio
import hashlib
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from kg_assistant.core.config import Settings
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.db.repositories.context import ContextRepository
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.evaluation.fixtures import fixture_runtime
from kg_assistant.evaluation.models import EvaluationDataset
from kg_assistant.evaluation.observations import ObservedQueryProvider, observe
from kg_assistant.evaluation.report import save_report, summarize
from kg_assistant.evaluation.repository import EvaluationRepository
from kg_assistant.evaluation.runner import EvaluationRuntime, evaluate_dataset
from kg_assistant.prompts.answer import ANSWER_INSTRUCTIONS
from kg_assistant.providers.answer import OpenAIAnswerProvider
from kg_assistant.providers.embeddings import OpenAIEmbeddingProvider
from kg_assistant.providers.query_entities import OpenAIQueryEntityProvider
from kg_assistant.retrieval.graph import GraphRetrievalService
from kg_assistant.retrieval.query_entities import QueryEntityExtractionService
from kg_assistant.retrieval.vector import VectorRetrievalService
from kg_assistant.services.embeddings import EmbeddingService


@asynccontextmanager
async def live_runtime(top_k: int):
    settings = Settings()
    if not settings.graphrag_enabled:
        raise ValueError("Enable embeddings, graph retrieval, and GraphRAG before live evaluation")
    if top_k > settings.vector_max_top_k:
        raise ValueError("top-k exceeds VECTOR_MAX_TOP_K")
    settings.vector_top_k = top_k
    async with AsyncExitStack() as stack:
        connection = Neo4jConnectionManager(settings)
        await connection.start()
        stack.push_async_callback(connection.close)
        embedding = OpenAIEmbeddingProvider(settings)
        stack.push_async_callback(embedding.close)
        query = OpenAIQueryEntityProvider(
            settings, lambda usage: observe("query_entity_extraction", usage)
        )
        stack.push_async_callback(query.close)
        answer = OpenAIAnswerProvider(settings, lambda usage: observe("answer_generation", usage))
        stack.push_async_callback(answer.close)
        vector = VectorRetrievalService(
            settings, VectorRepository(connection, settings), EmbeddingService(embedding, settings)
        )
        graph = GraphRetrievalService(
            settings,
            connection,
            QueryEntityExtractionService(settings, ObservedQueryProvider(query)),
        )
        yield EvaluationRuntime(
            settings,
            vector,
            graph,
            ContextRepository(connection, settings),
            answer,
            EvaluationRepository(connection, settings),
        )


def bounded_integer(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("Choose an integer from 1 to 100")
    return number


async def execute(args) -> dict:
    dataset_bytes = args.dataset.read_bytes()
    dataset = EvaluationDataset.model_validate_json(dataset_bytes)
    if args.mode == "mock":
        runtime = fixture_runtime(args.top_k)
        records = await evaluate_dataset(runtime, dataset, args.repeats)
        settings = runtime.settings
    else:
        async with live_runtime(args.top_k) as runtime:
            records = await evaluate_dataset(runtime, dataset, args.repeats)
            settings = runtime.settings
    payload = {
        "metadata": {
            "run_kind": "scripted_mock" if args.mode == "mock" else "live",
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_name": dataset.name,
            "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "answer_prompt_sha256": hashlib.sha256(ANSWER_INSTRUCTIONS.encode()).hexdigest(),
            "question_count": len(dataset.cases),
            "repeats": args.repeats,
            "top_k": args.top_k,
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "graph_max_hops": settings.graph_max_hops,
            "max_context_chunks": settings.max_context_chunks,
            "max_context_characters": settings.max_context_characters,
            "max_graph_paths": settings.max_graph_paths,
            "llm_max_attempts": settings.llm_max_attempts,
            "monetary_cost": None,
        },
        "questions": records,
        "summary": summarize(records),
    }
    output = args.output_dir or (
        Path("evaluation")
        if args.mode == "mock"
        else Path("evaluation/runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    save_report(payload, output)
    print(
        f"Saved {len(records)} paired observations to {output}/results.json and {output}/report.md"
    )
    print(
        "Scripted mock results are harness verification, not real AI quality."
        if args.mode == "mock"
        else (
            "Live results require manual semantic review; "
            "deterministic proxies are not semantic accuracy."
        )
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluation-only Vector RAG vs production GraphRAG"
    )
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/dataset.json"))
    parser.add_argument(
        "--mode",
        choices=["mock", "live"],
        default="mock",
        help="live calls configured paid providers against existing Neo4j data",
    )
    parser.add_argument("--top-k", type=bounded_integer, default=5)
    parser.add_argument("--repeats", type=bounded_integer, default=1)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    # Keep raw model/HTTP/document content out of console logs; raw evidence is in the
    # requested artifact.
    logging.basicConfig(level=logging.WARNING)
    try:
        payload = asyncio.run(execute(args))
    except Exception as exc:
        parser.exit(
            2,
            (
                f"Evaluation could not run ({type(exc).__name__}). Check "
                f"dataset/configuration; no successful results were fabricated.\n"
            ),
        )
    if any(
        record[mode]["status"] == "error"
        for record in payload["questions"]
        for mode in ["vector_rag", "graphrag"]
    ):
        parser.exit(
            1, "Some evaluation requests failed; inspect saved error codes and metric coverage.\n"
        )


if __name__ == "__main__":
    main()
