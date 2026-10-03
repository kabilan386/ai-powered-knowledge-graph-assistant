import type { SourceCitation } from "@/lib/types";
import { SourceCard } from "./source-card";
export function CitationList({
  sources,
  scope,
}: {
  sources: SourceCitation[];
  scope: string;
}) {
  if (!sources.length) return null;
  return (
    <section
      aria-label="Supporting sources"
      className="mt-6 border-t border-line pt-5"
    >
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted">
        Supporting sources{" "}
        <span className="ml-1 text-ink">{sources.length}</span>
      </h3>
      <div className="space-y-2">
        {sources.map((source) => (
          <SourceCard
            key={source.citation}
            source={source}
            id={`${scope}-${source.citation}`}
          />
        ))}
      </div>
    </section>
  );
}
