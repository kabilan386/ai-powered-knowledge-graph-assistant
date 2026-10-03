"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { api, errorMessage } from "@/lib/api";
import type { GraphNode, GraphResponse } from "@/lib/types";
import { connectedGraph, entityColors } from "@/lib/graph";
import { GraphLegend } from "./graph-legend";
import { ErrorState, LoadingState, PageHeader } from "@/components/ui/states";
import { Icon } from "@/components/ui/icon";
const KnowledgeGraph = dynamic(
  () => import("./knowledge-graph").then((module) => module.KnowledgeGraph),
  {
    ssr: false,
    loading: () => (
      <div className="p-10">
        <LoadingState>Preparing graph canvas…</LoadingState>
      </div>
    ),
  },
);
export function GraphWorkspace() {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [revision, setRevision] = useState(0);
  const [showIsolated, setShowIsolated] = useState(false);
  const linked = graph ? connectedGraph(graph) : null;
  const visible =
    graph && linked
      ? showIsolated || !linked.nodes.length
        ? graph
        : linked
      : null;
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError(null);
      setGraph(null);
      setSelected(null);
      try {
        const data = await api.graph(controller.signal);
        if (!controller.signal.aborted) setGraph(data);
      } catch (cause) {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [revision]);
  const connected =
    selected && graph
      ? graph.edges.filter(
          (edge) => edge.source === selected.id || edge.target === selected.id,
        )
      : [];
  return (
    <>
      <PageHeader
        eyebrow="SEE THE CONNECTIONS"
        title="Knowledge, mapped."
        description="Explore the entities and relationships extracted from your documents. Select a node to look closer."
        action={
          <button
            className="btn-secondary"
            disabled={loading}
            onClick={() => setRevision((current) => current + 1)}
          >
            <Icon name="refresh" />
            Refresh graph
          </button>
        }
      />
      {loading ? (
        <div className="panel p-10">
          <LoadingState>Loading the knowledge graph…</LoadingState>
        </div>
      ) : error ? (
        <ErrorState
          message={error}
          retry={() => setRevision((current) => current + 1)}
        />
      ) : graph && !graph.nodes.length ? (
        <div className="panel p-12 text-center">
          <div className="empty-mark mx-auto">
            <Icon name="graph" width={34} height={34} />
          </div>
          <h2 className="mt-5 text-xl font-semibold">
            Your graph is ready to grow
          </h2>
          <p className="mt-3 text-muted">
            Upload a document with entity extraction enabled to create connected
            knowledge.
          </p>
          <Link className="btn-primary mt-6" href="/documents">
            Add a document
            <Icon name="arrow" />
          </Link>
        </div>
      ) : (
        graph && (
          <>
            {graph.truncated && (
              <p role="status" className="notice mb-5">
                Showing a bounded snapshot (up to 100 entities and 200
                relationships). Some graph data is outside this view.
              </p>
            )}
            <div className="graph-layout">
              <section className="panel overflow-hidden">
                <div className="graph-toolbar">
                  <h2 className="font-semibold text-sm">
                    Entity relationships
                  </h2>
                  <span className="text-xs text-muted">
                    {graph.nodes.length} entities · {graph.edges.length}{" "}
                    relationships
                  </span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3 text-sm">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={showIsolated}
                      onChange={(event) =>
                        setShowIsolated(event.target.checked)
                      }
                    />
                    Include isolated entities
                  </label>
                  <span className="text-muted">
                    Showing {visible?.nodes.length} of {graph.nodes.length}{" "}
                    entities
                    {linked &&
                    linked.nodes.length > 0 &&
                    !showIsolated &&
                    linked.nodes.length < graph.nodes.length
                      ? ` · ${graph.nodes.length - linked.nodes.length} isolated entities available in the list`
                      : ""}
                  </span>
                </div>
                {visible && (
                  <KnowledgeGraph graph={visible} onSelect={setSelected} />
                )}
                <GraphLegend types={graph.nodes.map((node) => node.type)} />
              </section>
              <aside className="panel p-5">
                <h2 className="eyebrow mb-4">ENTITY DETAILS</h2>
                {selected ? (
                  <>
                    <span
                      className="badge"
                      style={{
                        color:
                          entityColors[selected.type] ?? entityColors.OTHER,
                      }}
                    >
                      {selected.type.replaceAll("_", " ")}
                    </span>
                    <h3 className="mt-3 text-xl font-semibold break-words">
                      {selected.label}
                    </h3>
                    <p className="mt-3 text-sm leading-relaxed text-muted">
                      {selected.description ||
                        "No description is available for this entity."}
                    </p>
                    <p className="mt-3 break-all text-xs text-muted">
                      ID: {selected.id}
                    </p>
                    <h4 className="mt-6 mb-3 text-xs font-semibold uppercase tracking-wider text-muted">
                      Connected relationships
                    </h4>
                    {connected.length ? (
                      <ul className="space-y-3 text-sm">
                        {connected.map((edge) => (
                          <li key={edge.id} className="break-words">
                            <span>
                              {
                                graph.nodes.find(
                                  (node) => node.id === edge.source,
                                )?.label
                              }
                            </span>
                            <span className="block text-xs font-semibold text-accent my-1">
                              → {edge.type} →
                            </span>
                            <span>
                              {
                                graph.nodes.find(
                                  (node) => node.id === edge.target,
                                )?.label
                              }
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-muted">
                        No relationships in this snapshot.
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm leading-relaxed text-muted">
                    Select an entity on the canvas or from the list below to see
                    its details.
                  </p>
                )}
                <details className="mt-6 border-t border-line pt-4">
                  <summary className="text-sm font-medium cursor-pointer">
                    Browse entities ({graph.nodes.length})
                  </summary>
                  <ul className="mt-3 max-h-64 overflow-auto space-y-1">
                    {graph.nodes.map((node) => (
                      <li key={node.id}>
                        <button
                          className="entity-list-button"
                          onClick={() => setSelected(node)}
                          aria-pressed={selected?.id === node.id}
                        >
                          <span
                            className="legend-dot shrink-0"
                            style={{
                              backgroundColor:
                                entityColors[node.type] ?? entityColors.OTHER,
                            }}
                          />
                          {node.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                </details>
              </aside>
            </div>
          </>
        )
      )}
    </>
  );
}
