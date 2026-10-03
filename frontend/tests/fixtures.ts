import type {
  GraphRAGResponse,
  UploadResponse,
  GraphResponse,
} from "@/lib/types";
export const answer: GraphRAGResponse = {
  question: "What does Payment Service use?",
  answer: "Payment Service uses Redis [S1].",
  citations: ["S1"],
  insufficient_evidence: false,
  sources: [
    {
      citation: "S1",
      kind: "document",
      document_id: "doc-1",
      chunk_id: "chunk-1",
      filename: "architecture.pdf",
      page_number: 3,
      chunk_index: 7,
      excerpt: "Payment Service uses Redis for caching.",
      excerpt_truncated: false,
      nodes: [],
      edges: [],
      supporting_citations: [],
    },
  ],
  retrieval: {
    vector_results: 3,
    graph_paths: 1,
    context_chunks: 1,
    context_graph_paths: 1,
    context_characters: 200,
    vector_top_k: 5,
    graph_max_hops: 3,
    graph_status: "ok",
    graph_truncated: false,
    context_truncated: false,
    duration_ms: 123,
  },
};
export const upload: UploadResponse = {
  document: {
    id: "doc-1",
    filename: "architecture.pdf",
    file_type: "pdf",
    created_at: "2026-10-03T00:00:00Z",
    extraction_status: "completed",
  },
  chunk_count: 12,
  extraction: {
    status: "completed",
    completed: 12,
    total: 12,
    failed: 0,
    errors: [],
  },
  embeddings: {
    status: "completed",
    completed: 12,
    total: 12,
    failed: 0,
    errors: [],
  },
};
export const graph: GraphResponse = {
  nodes: [
    {
      id: "team",
      label: "Platform Team",
      type: "ORGANIZATION",
      description: "Owns the platform.",
    },
    {
      id: "service",
      label: "Payment Service",
      type: "SERVICE",
      description: null,
    },
  ],
  edges: [{ id: "fact", source: "team", target: "service", type: "MANAGES" }],
  truncated: false,
};
