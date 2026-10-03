from kg_assistant.core.config import Settings
from kg_assistant.models.graph_retrieval import GraphPath, GraphSearchResponse
from kg_assistant.models.graphrag import (
    FusedContext,
    FusedEdge,
    GraphEvidence,
    SourceChunk,
    TextEvidence,
)
from kg_assistant.models.retrieval import VectorSearchResponse


def path_identity(path: GraphPath) -> tuple:
    return (
        tuple(node.id for node in path.nodes),
        tuple((edge.source_id, edge.type, edge.target_id) for edge in path.edges),
    )


class ContextBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def select_paths(self, graph: GraphSearchResponse) -> list[GraphPath]:
        unique = {}
        support_by_edge = {}
        for path in sorted(graph.paths, key=lambda p: (-p.score, p.hop_count, path_identity(p))):
            unique.setdefault(path_identity(path), path)
            for edge in path.edges:
                key = (edge.source_id, edge.type, edge.target_id)
                records = support_by_edge.setdefault(key, {})
                for evidence in edge.evidence:
                    records.setdefault(
                        (
                            evidence.document_id,
                            evidence.chunk_id,
                            evidence.relationship_id,
                            evidence.evidence_quote,
                        ),
                        evidence,
                    )
        for identity, path in list(unique.items()):
            merged = []
            for edge in path.edges:
                records = list(
                    support_by_edge[(edge.source_id, edge.type, edge.target_id)].values()
                )
                merged.append(
                    edge.model_copy(
                        update={
                            "evidence": records[: self.settings.graph_max_evidence],
                            "evidence_truncated": edge.evidence_truncated
                            or len(records) > self.settings.graph_max_evidence,
                        }
                    )
                )
            unique[identity] = path.model_copy(update={"edges": merged})
        paths = list(unique.values())
        complementary = [
            path
            for path in paths
            if not any(
                len(other.edges) > len(path.edges)
                and path_identity(other)[0][: len(path.nodes)] == path_identity(path)[0]
                and path_identity(other)[1][: len(path.edges)] == path_identity(path)[1]
                for other in paths
            )
        ]
        return complementary[: self.settings.max_graph_paths]

    def references(
        self, vector: VectorSearchResponse, graph: GraphSearchResponse
    ) -> list[tuple[str, str]]:
        references = {(item.document_id, item.chunk_id) for item in vector.results}
        for path in self.select_paths(graph):
            for edge in path.edges:
                for evidence in edge.evidence:
                    if evidence.document_id and evidence.chunk_id:
                        references.add((evidence.document_id, evidence.chunk_id))
        return sorted(references)

    def build(
        self, vector: VectorSearchResponse, graph: GraphSearchResponse, chunks: list[SourceChunk]
    ) -> FusedContext:
        available = {(chunk.document_id, chunk.chunk_id): chunk for chunk in chunks}
        paths = self.select_paths(graph)
        scores = {}
        for result in vector.results:
            key = (result.document_id, result.chunk_id)
            scores[key] = max(scores.get(key, -1), result.score)
        # Shared evidence first, then strongest text, then complementary graph sources.
        graph_keys = []
        for path in paths:
            for edge in path.edges:
                for evidence in edge.evidence:
                    key = (evidence.document_id, evidence.chunk_id)
                    if key in available and key not in graph_keys:
                        graph_keys.append(key)
        ordered = sorted(scores, key=lambda key: (key not in graph_keys, -scores[key], key))
        ordered.extend(key for key in graph_keys if key not in scores)
        context = FusedContext(
            truncated=len(paths) < len(graph.paths)
            or any(edge.evidence_truncated for path in paths for edge in path.edges)
        )
        citation_keys = {}
        for key in ordered:
            chunk = available.get(key)
            if chunk is None:
                context.truncated = True
                continue
            if len(context.text_evidence) >= self.settings.max_context_chunks:
                context.truncated = True
                break
            excerpt = chunk.text[: self.settings.max_chunk_context_characters]
            item = TextEvidence(
                citation=f"S{len(context.text_evidence) + 1}",
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                excerpt=excerpt,
                excerpt_truncated=chunk.text_truncated or len(excerpt) < len(chunk.text),
                vector_score=scores.get(key),
            )
            context.text_evidence.append(item)
            text_budget = (
                int(self.settings.max_context_characters * 0.7)
                if paths
                else self.settings.max_context_characters
            )
            if len(context.payload()) > text_budget:
                context.text_evidence.pop()
                context.truncated = True
                continue
            citation_keys[key] = item.citation
            context.truncated |= item.excerpt_truncated
        for path in paths:
            edges = []
            for edge in path.edges:
                support = []
                for evidence in edge.evidence:
                    key = (evidence.document_id, evidence.chunk_id)
                    citation = citation_keys.get(key)
                    if citation is None:
                        continue
                    source = next(
                        text for text in context.text_evidence if text.citation == citation
                    )
                    # Document support requires a quote in the supplied source excerpt.
                    if evidence.evidence_quote and evidence.evidence_quote in source.excerpt:
                        if citation not in support:
                            support.append(citation)
                edges.append(
                    FusedEdge(
                        type=edge.type,
                        source_id=edge.source_id,
                        target_id=edge.target_id,
                        source_citations=support,
                        document_backed=bool(support),
                    )
                )
            item = GraphEvidence(
                citation=f"G{len(context.graph_evidence) + 1}",
                hop_count=path.hop_count,
                nodes=path.nodes,
                edges=edges,
            )
            context.graph_evidence.append(item)
            if len(context.payload()) > self.settings.max_context_characters:
                context.graph_evidence.pop()
                context.truncated = True
        return context
