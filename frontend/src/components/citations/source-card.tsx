import type { SourceCitation } from "@/lib/types";
export function SourceCard({
  source,
  id,
}: {
  source: SourceCitation;
  id: string;
}) {
  return (
    <details id={id} className="source-card">
      <summary>
        <span className="citation-label">[{source.citation}]</span>
        <span className="min-w-0">
          <span className="block font-medium break-words">
            {source.kind === "document"
              ? (source.filename ?? "Document source")
              : "Knowledge graph path"}
          </span>
          <span className="mt-1 block text-xs text-muted">
            {source.kind === "document"
              ? `${source.page_number !== null ? `Page ${source.page_number} · ` : ""}${source.chunk_index !== null ? `Chunk ${source.chunk_index}` : "Source chunk"}`
              : `${source.edges.length} relationships · ${source.supporting_citations.length ? "Document support available" : "No document provenance supplied"}`}
          </span>
        </span>
        <span className="ml-auto text-xs text-muted">View evidence</span>
      </summary>
      <div className="source-body">
        {source.kind === "document" ? (
          <>
            <p className="whitespace-pre-wrap leading-relaxed">
              {source.excerpt ?? "No supporting excerpt was provided."}
            </p>
            {source.excerpt_truncated && (
              <p className="mt-2 text-xs text-muted">
                Excerpt shortened by the backend.
              </p>
            )}
            <dl className="mt-4 space-y-1 text-xs text-muted">
              <div>
                <dt className="inline">Document ID: </dt>
                <dd className="inline break-all">
                  {source.document_id ?? "Unavailable"}
                </dd>
              </div>
              <div>
                <dt className="inline">Chunk ID: </dt>
                <dd className="inline break-all">
                  {source.chunk_id ?? "Unavailable"}
                </dd>
              </div>
            </dl>
          </>
        ) : (
          <>
            <p className="text-sm text-muted mb-3">
              Graph facts preserve their stored direction. A graph citation is
              not itself a document citation.
            </p>
            {source.edges.map((edge, index) => (
              <p
                key={`${edge.source_id}-${edge.type}-${edge.target_id}-${index}`}
                className="mb-2 break-words text-sm"
              >
                {source.nodes.find((node) => node.id === edge.source_id)
                  ?.name ?? edge.source_id}{" "}
                <span className="font-semibold text-accent">
                  → {edge.type} →
                </span>{" "}
                {source.nodes.find((node) => node.id === edge.target_id)
                  ?.name ?? edge.target_id}
                {edge.document_backed && (
                  <span className="text-muted">
                    {" "}
                    {edge.source_citations
                      .map((citation) => `[${citation}]`)
                      .join(" ")}
                  </span>
                )}
              </p>
            ))}
            {!!source.supporting_citations.length && (
              <p className="mt-3 text-xs text-muted">
                Supporting document sources:{" "}
                {source.supporting_citations
                  .map((citation) => `[${citation}]`)
                  .join(" ")}
              </p>
            )}
          </>
        )}
      </div>
    </details>
  );
}
