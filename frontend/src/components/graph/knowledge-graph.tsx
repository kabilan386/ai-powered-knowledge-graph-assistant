"use client";
import { useEffect, useRef } from "react";
import cytoscape, { type Core } from "cytoscape";
import type { GraphNode, GraphResponse } from "@/lib/types";
import { graphElements } from "@/lib/graph";
import { Icon } from "@/components/ui/icon";
export function KnowledgeGraph({
  graph,
  onSelect,
}: {
  graph: GraphResponse;
  onSelect: (node: GraphNode) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);
  const selection = useRef(onSelect);
  useEffect(() => {
    selection.current = onSelect;
  }, [onSelect]);
  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      elements: graphElements(graph),
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.25,
      layout: graph.edges.length
        ? {
            name: "cose",
            animate: false,
            padding: 70,
            nodeDimensionsIncludeLabels: true,
            componentSpacing: 140,
            nodeRepulsion: () => 12000,
            idealEdgeLength: () => 170,
            edgeElasticity: () => 100,
            gravity: 0.3,
            numIter: 1000,
            randomize: false,
          }
        : {
            name: "grid",
            padding: 60,
            avoidOverlap: true,
            nodeDimensionsIncludeLabels: true,
            spacingFactor: 1.3,
          },
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            label: "data(label)",
            color: "#243a32",
            "font-size": 12,
            "font-family": "Arial, sans-serif",
            "text-valign": "bottom",
            "text-margin-y": 10,
            "text-wrap": "wrap",
            "text-max-width": "125px",
            width: 42,
            height: 42,
            "border-width": 4,
            "border-color": "#fff",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#bac9c2",
            "target-arrow-color": "#8b9f95",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 11,
            color: "#5f756a",
            "text-background-color": "#f9fbf8",
            "text-background-opacity": 1,
            "text-background-padding": "4px",
            "text-rotation": "autorotate",
            "arrow-scale": 0.8,
          },
        },
        {
          selector: "node:selected",
          style: { "border-color": "#173e30", "border-width": 5 },
        },
      ],
    });
    instance.current = cy;
    cy.on("tap", "node", (event) => {
      const id: string = event.target.data("entityId");
      const node = graph.nodes.find((item) => item.id === id);
      if (node) selection.current(node);
    });
    const observer = new ResizeObserver(() => {
      cy.resize();
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      cy.destroy();
      instance.current = null;
    };
  }, [graph]);
  function zoom(multiplier: number) {
    const cy = instance.current;
    if (cy)
      cy.zoom({
        level: Math.max(
          cy.minZoom(),
          Math.min(cy.maxZoom(), cy.zoom() * multiplier),
        ),
        renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
      });
  }
  return (
    <div className="graph-canvas-wrapper">
      <div
        ref={container}
        role="img"
        aria-label="Interactive knowledge graph. Use the entity list to inspect nodes with a keyboard."
        className="graph-canvas"
      />
      <div className="graph-controls">
        <button
          className="icon-button"
          title="Zoom in"
          aria-label="Zoom in"
          onClick={() => zoom(1.2)}
        >
          <Icon name="plus" />
        </button>
        <button
          className="icon-button"
          title="Zoom out"
          aria-label="Zoom out"
          onClick={() => zoom(1 / 1.2)}
        >
          <Icon name="minus" />
        </button>
        <button
          className="icon-button"
          title="Fit graph"
          aria-label="Fit graph"
          onClick={() => instance.current?.fit(undefined, 55)}
        >
          <Icon name="fit" />
        </button>
      </div>
      <p className="graph-hint">
        Drag to pan · Scroll to zoom · Select an entity
      </p>
    </div>
  );
}
