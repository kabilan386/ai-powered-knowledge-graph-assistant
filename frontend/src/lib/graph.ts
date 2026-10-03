import type { ElementDefinition } from "cytoscape";
import type { GraphResponse } from "./types";
export const entityColors: Record<string, string> = {
  PERSON: "#be526a",
  ORGANIZATION: "#226b52",
  PROJECT: "#94723b",
  SERVICE: "#4467ae",
  TECHNOLOGY: "#7957ac",
  DATABASE: "#ad5c28",
  CLOUD_SERVICE: "#168496",
  LOCATION: "#668243",
  CONCEPT: "#a1607d",
  OTHER: "#697a83",
};
export function graphElements(graph: GraphResponse): ElementDefinition[] {
  const nodes = [
    ...new Map(graph.nodes.map((node) => [node.id, node])).values(),
  ];
  const ids = new Set(nodes.map((node) => node.id));
  return [
    ...nodes.map((node) => ({
      data: {
        ...node,
        id: `node:${node.id}`,
        entityId: node.id,
        color: entityColors[node.type] ?? entityColors.OTHER,
      },
    })),
    ...[...new Map(graph.edges.map((edge) => [edge.id, edge])).values()]
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge) => ({
        data: {
          ...edge,
          id: `edge:${edge.id}`,
          source: `node:${edge.source}`,
          target: `node:${edge.target}`,
          label: edge.type.replaceAll("_", " "),
        },
      })),
  ];
}

export function connectedGraph(graph: GraphResponse): GraphResponse {
  const ids = new Set(graph.nodes.map((node) => node.id));
  const edges = graph.edges.filter(
    (edge) => ids.has(edge.source) && ids.has(edge.target),
  );
  const connected = new Set(
    edges.flatMap((edge) => [edge.source, edge.target]),
  );
  return {
    ...graph,
    nodes: graph.nodes.filter((node) => connected.has(node.id)),
    edges,
  };
}
