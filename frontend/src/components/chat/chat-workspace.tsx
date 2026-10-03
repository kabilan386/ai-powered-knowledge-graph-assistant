"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, errorMessage } from "@/lib/api";
import type { GraphRAGResponse } from "@/lib/types";
import { ChatInput } from "./chat-input";
import { AnswerCard } from "./answer-card";
import { ErrorState, LoadingState, PageHeader } from "@/components/ui/states";
import { Icon } from "@/components/ui/icon";
interface Turn {
  id: string;
  question: string;
  response?: GraphRAGResponse;
  error?: string;
}
const suggestions = [
  "What does Payment Service use?",
  "Which cloud service hosts the technology used by the service managed by Platform Team?",
  "What service is managed by Platform Team?",
];
export function ChatWorkspace() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (turns.length)
      bottom.current?.scrollIntoView?.({
        behavior: "smooth",
        block: "nearest",
      });
  }, [turns, loading]);
  async function submit() {
    const text = question.trim();
    if (!text || controller.current) return;
    const id = crypto.randomUUID();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setQuestion("");
    setTurns((current) => [...current, { id, question: text }]);
    try {
      const response = await api.ask({ question: text }, request.signal);
      if (!request.signal.aborted)
        setTurns((current) =>
          current.map((turn) =>
            turn.id === id ? { ...turn, response } : turn,
          ),
        );
    } catch (error) {
      if (!request.signal.aborted) {
        setTurns((current) =>
          current.map((turn) =>
            turn.id === id ? { ...turn, error: errorMessage(error) } : turn,
          ),
        );
        setQuestion(text);
      }
    } finally {
      if (!request.signal.aborted) setLoading(false);
      controller.current = null;
    }
  }
  return (
    <>
      <PageHeader
        eyebrow="YOUR KNOWLEDGE, CONNECTED"
        title="Ask. Explore. Understand."
        description="Find answers across your documents and the relationships between them. Every supported answer comes with evidence."
        action={
          <Link href="/documents" className="btn-secondary">
            <Icon name="upload" />
            Add documents
          </Link>
        }
      />
      <div className="chat-workspace">
        {!turns.length ? (
          <section className="chat-empty">
            <div className="empty-mark">
              <Icon name="graph" width={36} height={36} />
            </div>
            <h2>What would you like to discover?</h2>
            <p>
              Start with a question. The assistant searches your documents
              <br className="hidden md:block" /> and follows connected knowledge
              to find supporting evidence.
            </p>
            <div className="suggestions">
              {suggestions.map((suggestion, index) => (
                <button
                  key={suggestion}
                  onClick={() => setQuestion(suggestion)}
                  className="suggestion"
                >
                  <span className="eyebrow">
                    {
                      [
                        "EXPLORE A SERVICE",
                        "FOLLOW CONNECTIONS",
                        "DISCOVER OWNERSHIP",
                      ][index]
                    }
                  </span>
                  <span className="mt-2 block text-sm leading-relaxed">
                    {suggestion}
                  </span>
                  <Icon
                    name="arrow"
                    className="mt-4 text-accent"
                    width={17}
                    height={17}
                  />
                </button>
              ))}
            </div>
            <p className="text-xs mt-6">
              These example questions work after uploading the sample document.
            </p>
          </section>
        ) : (
          <div className="space-y-7 pb-7" aria-live="polite">
            {turns.map((turn) => (
              <div key={turn.id}>
                <div className="user-question">
                  <span className="eyebrow mb-2 block">YOU</span>
                  <p className="whitespace-pre-wrap break-words">
                    {turn.question}
                  </p>
                </div>
                {turn.response && (
                  <AnswerCard
                    response={turn.response}
                    scope={`answer-${turn.id}`}
                  />
                )}
                {turn.error && <ErrorState message={turn.error} />}
              </div>
            ))}
            {loading && (
              <div className="panel p-5">
                <LoadingState>
                  Searching documents and connected knowledge…
                </LoadingState>
              </div>
            )}
            <div ref={bottom} />
          </div>
        )}
        <ChatInput
          value={question}
          onChange={setQuestion}
          onSubmit={submit}
          loading={loading}
        />
        <p className="mt-3 text-center text-xs text-muted">
          Check the cited evidence before relying on an answer.
        </p>
      </div>
    </>
  );
}
