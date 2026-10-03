export interface GraphRAGRequest {
  question: string;
}
export interface GraphEntity {
  id: string;
  name: string;
  type: string;
}
export interface FusedEdge {
  type: string;
  source_id: string;
  target_id: string;
  source_citations: string[];
  document_backed: boolean;
}
export interface SourceCitation {
  citation: string;
  kind: "document" | "graph";
  document_id: string | null;
  chunk_id: string | null;
  filename: string | null;
  page_number: number | null;
  chunk_index: number | null;
  excerpt: string | null;
  excerpt_truncated: boolean;
  nodes: GraphEntity[];
  edges: FusedEdge[];
  supporting_citations: string[];
}
export interface GraphRAGResponse {
  question: string;
  answer: string;
  citations: string[];
  sources: SourceCitation[];
  insufficient_evidence: boolean;
  retrieval: {
    vector_results: number;
    graph_paths: number;
    context_chunks: number;
    context_graph_paths: number;
    context_characters: number;
    vector_top_k: number;
    graph_max_hops: number;
    graph_status: string;
    graph_truncated: boolean;
    context_truncated: boolean;
    duration_ms: number;
  };
}
export type ProcessingStatus =
  "disabled" | "pending" | "processing" | "completed" | "partial" | "failed";
export interface Document {
  id: string;
  filename: string;
  file_type: "pdf" | "docx" | "txt";
  created_at: string;
  extraction_status: ProcessingStatus;
}
export interface ProcessingSummary {
  status: ProcessingStatus;
  total: number;
  completed: number;
  failed: number;
  errors: { chunk_id: string; code: string; attempts?: number }[];
}
export interface UploadResponse {
  document: Document;
  chunk_count: number;
  extraction: ProcessingSummary;
  embeddings: ProcessingSummary;
}
export interface GraphNode {
  id: string;
  label: string;
  type: string;
  description: string | null;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}
export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}
