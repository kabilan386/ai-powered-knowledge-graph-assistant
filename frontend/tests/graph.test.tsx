import type { GraphNode, GraphResponse } from "@/lib/types";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import { connectedGraph, graphElements } from "@/lib/graph";
import { GraphWorkspace } from "@/components/graph/graph-workspace";
import { graph } from "./fixtures";
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { graph: vi.fn() },
}));
vi.mock("next/dynamic", () => ({
  default: () =>
    function Canvas({
      graph: data,
      onSelect,
    }: {
      graph: GraphResponse;
      onSelect: (node: GraphNode) => void;
    }) {
      return (
        <button onClick={() => onSelect(data.nodes[0])}>
          Select canvas node
        </button>
      );
    },
}));
describe("Knowledge graph", () => {
  it("keeps connected entities without changing the full snapshot", () => {
    const data = {
      ...graph,
      nodes: [
        ...graph.nodes,
        { id: "alone", label: "Isolated", type: "OTHER", description: null },
      ],
    };
    expect(connectedGraph(data).nodes).toHaveLength(2);
    expect(data.nodes).toHaveLength(3);
  });
  it("can include isolated entities in the canvas", async () => {
    vi.mocked(api.graph).mockResolvedValue({
      ...graph,
      nodes: [
        ...graph.nodes,
        { id: "alone", label: "Isolated", type: "OTHER", description: null },
      ],
    });
    render(<GraphWorkspace />);
    expect(await screen.findByText(/Showing 2 of 3 entities/)).toBeVisible();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Include isolated entities" }),
    );
    expect(screen.getByText(/Showing 3 of 3 entities/)).toBeVisible();
  });
  it("maps actual nodes, directions, colors and edge labels", () => {
    const elements = graphElements(graph);
    expect(elements).toHaveLength(3);
    expect(elements[0].data).toMatchObject({
      id: "node:team",
      label: "Platform Team",
      entityId: "team",
      color: "#226b52",
    });
    expect(elements[2].data).toMatchObject({
      id: "edge:fact",
      source: "node:team",
      target: "node:service",
      label: "MANAGES",
    });
  });
  it("deduplicates IDs and omits dangling edges without inventing nodes", () => {
    const elements = graphElements({
      ...graph,
      nodes: [...graph.nodes, graph.nodes[0]],
      edges: [
        ...graph.edges,
        graph.edges[0],
        { id: "bad", source: "team", target: "missing", type: "USES" },
      ],
    });
    expect(elements).toHaveLength(3);
    expect(graphElements({ nodes: [], edges: [], truncated: false })).toEqual(
      [],
    );
  });
  it("loads real response nodes and displays node details", async () => {
    vi.mocked(api.graph).mockResolvedValue(graph);
    render(<GraphWorkspace />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    fireEvent.click(
      await screen.findByRole("button", { name: "Select canvas node" }),
    );
    expect(screen.getByText("Owns the platform.")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Platform Team" }),
    ).toBeVisible();
    expect(screen.getByText("2 entities · 1 relationships")).toBeVisible();
  });
  it("shows empty graph state and error retry", async () => {
    vi.mocked(api.graph)
      .mockResolvedValueOnce({ nodes: [], edges: [], truncated: false })
      .mockRejectedValueOnce(new Error("Graph unavailable"))
      .mockResolvedValueOnce(graph);
    render(<GraphWorkspace />);
    expect(
      await screen.findByText("Your graph is ready to grow"),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh graph" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Graph unavailable",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Select canvas node" }),
      ).toBeVisible(),
    );
  });
  it("communicates bounded snapshots", async () => {
    vi.mocked(api.graph).mockResolvedValue({ ...graph, truncated: true });
    render(<GraphWorkspace />);
    expect(await screen.findByText(/Showing a bounded snapshot/)).toBeVisible();
  });
});
