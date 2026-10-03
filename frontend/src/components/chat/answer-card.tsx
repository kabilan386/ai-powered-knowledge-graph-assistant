import type { GraphRAGResponse } from "@/lib/types";
import { CitationList } from "@/components/citations/citation-list";
import { Icon } from "@/components/ui/icon";
export function AnswerCard({
  response,
  scope,
}: {
  response: GraphRAGResponse;
  scope: string;
}) {
  const valid = new Set(
    response.citations.filter((citation) =>
      response.sources.some((source) => source.citation === citation),
    ),
  );
  return (
    <article className="answer-card">
      <div className="mb-4 flex items-center gap-2">
        <span className="answer-avatar">
          <Icon name="graph" width={17} height={17} />
        </span>
        <h2 className="font-semibold text-sm">Knowledge Assistant</h2>
        <span
          className={`ml-auto badge ${response.insufficient_evidence ? "badge-warning" : ""}`}
        >
          {response.insufficient_evidence
            ? "Insufficient evidence"
            : "Evidence-based answer"}
        </span>
      </div>
      <p className="whitespace-pre-wrap leading-8 text-ink">
        {response.answer.split(/(\[[SG]\d+\])/g).map((part, index) => {
          const citation = part.slice(1, -1);
          return valid.has(citation) && part.startsWith("[") ? (
            <a
              key={index}
              className="inline-citation"
              href={`#${scope}-${citation}`}
              onClick={() => {
                const element = document.getElementById(`${scope}-${citation}`);
                if (element instanceof HTMLDetailsElement) element.open = true;
              }}
            >
              {part}
            </a>
          ) : (
            <span key={index}>{part}</span>
          );
        })}
      </p>
      <CitationList sources={response.sources} scope={scope} />
      <p className="mt-5 text-xs text-muted">
        Retrieved {response.retrieval.vector_results} text matches ·{" "}
        {response.retrieval.graph_paths} graph paths
        {(response.retrieval.context_truncated ||
          response.retrieval.graph_truncated) &&
          " · Evidence limited by retrieval bounds"}
      </p>
    </article>
  );
}
