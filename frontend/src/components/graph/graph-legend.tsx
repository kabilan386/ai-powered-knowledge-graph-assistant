import { entityColors } from "@/lib/graph";
export function GraphLegend({ types }: { types: string[] }) {
  return (
    <div className="graph-legend" aria-label="Entity type legend">
      {[...new Set(types)].sort().map((type) => (
        <span key={type} className="flex items-center gap-2 text-xs text-muted">
          <span
            className="legend-dot"
            style={{
              backgroundColor: entityColors[type] ?? entityColors.OTHER,
            }}
          />
          {type.replaceAll("_", " ")}
        </span>
      ))}
    </div>
  );
}
