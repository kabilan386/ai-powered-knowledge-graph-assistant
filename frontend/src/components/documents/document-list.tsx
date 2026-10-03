import type { UploadResponse } from "@/lib/types";
import { Icon } from "@/components/ui/icon";
export function DocumentList({ documents }: { documents: UploadResponse[] }) {
  return (
    <section className="panel mt-7">
      <div className="border-b border-line p-6">
        <h2 className="font-semibold">
          Uploads this session{" "}
          <span className="ml-2 badge">{documents.length}</span>
        </h2>
        <p className="mt-2 text-xs text-muted">
          Documents stay in Neo4j. This list tracks uploads while this browser
          workspace is open; it resets on reload.
        </p>
      </div>
      {!documents.length ? (
        <div className="p-10 text-center text-muted">
          <Icon
            name="document"
            className="mx-auto mb-3"
            width={28}
            height={28}
          />
          <p className="font-medium text-ink">
            No documents uploaded in this session
          </p>
          <p className="mt-2 text-sm">Add a document above to get started.</p>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {documents.map((item) => (
            <li key={item.document.id} className="p-6">
              <div className="flex flex-wrap items-center gap-3">
                <span className="file-type">
                  {item.document.file_type.toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="break-words font-medium">
                    {item.document.filename}
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    {item.chunk_count} chunks ·{" "}
                    {new Date(item.document.created_at).toLocaleString()}
                  </p>
                </div>
                <span className="badge">Text stored</span>
              </div>
              <div className="mt-4 flex flex-wrap gap-3 text-xs">
                <span>
                  Graph extraction: <strong>{item.extraction.status}</strong> (
                  {item.extraction.completed}/{item.extraction.total})
                </span>
                <span>
                  Embeddings: <strong>{item.embeddings.status}</strong> (
                  {item.embeddings.completed}/{item.embeddings.total})
                </span>
              </div>
              {[...item.extraction.errors, ...item.embeddings.errors].length >
                0 && (
                <details className="mt-3 text-xs text-danger">
                  <summary className="cursor-pointer">
                    Processing errors
                  </summary>
                  <ul className="mt-2 space-y-1">
                    {[...item.extraction.errors, ...item.embeddings.errors].map(
                      (error, index) => (
                        <li key={index}>
                          {error.code} · chunk {error.chunk_id}
                        </li>
                      ),
                    )}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
