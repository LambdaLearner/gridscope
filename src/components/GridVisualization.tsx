interface GridVisualizationProps {
  rows: number;
  cols: number;
  overlapPercent: number;
}

export function GridVisualization({ rows, cols, overlapPercent }: GridVisualizationProps) {
  const svgSize = 400;
  const padding = 40;
  const availableSize = svgSize - 2 * padding;

  const tileSize = availableSize / Math.max(rows, cols);
  const overlapOffset = tileSize * (overlapPercent / 100);

  const tiles = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      tiles.push({ row, col });
    }
  }

  return (
    <div className="flex flex-col items-center">
      <svg
        width={svgSize}
        height={svgSize}
        viewBox={`0 0 ${svgSize} ${svgSize}`}
        className="border border-gray-200 rounded-lg bg-gray-50"
      >
        <defs>
          <pattern
            id="grid"
            width={tileSize}
            height={tileSize}
            patternUnits="userSpaceOnUse"
          >
            <path
              d={`M ${tileSize} 0 L 0 0 0 ${tileSize}`}
              fill="none"
              stroke="#e5e7eb"
              strokeWidth="0.5"
            />
          </pattern>
        </defs>

        <rect
          width={svgSize}
          height={svgSize}
          fill="url(#grid)"
        />

        {tiles.map(({ row, col }) => {
          const x = padding + col * (tileSize - overlapOffset);
          const y = padding + row * (tileSize - overlapOffset);
          const isEdge = row === 0 || col === 0 || row === rows - 1 || col === cols - 1;

          return (
            <g key={`${row}-${col}`}>
              <rect
                x={x}
                y={y}
                width={tileSize}
                height={tileSize}
                fill={isEdge ? '#dbeafe' : '#f0f9ff'}
                stroke="#3b82f6"
                strokeWidth="1.5"
                opacity="0.8"
              />
              <text
                x={x + tileSize / 2}
                y={y + tileSize / 2}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="10"
                fill="#1e40af"
                fontWeight="500"
              >
                {row * cols + col}
              </text>
            </g>
          );
        })}

        {overlapPercent > 0 && (
          <>
            <line
              x1={padding + tileSize}
              y1={padding + 5}
              x2={padding + tileSize}
              y2={padding + tileSize - 5}
              stroke="#ef4444"
              strokeWidth="1"
              strokeDasharray="2,2"
            />
            <line
              x1={padding + tileSize - overlapOffset}
              y1={padding + 5}
              x2={padding + tileSize - overlapOffset}
              y2={padding + tileSize - 5}
              stroke="#ef4444"
              strokeWidth="1"
              strokeDasharray="2,2"
            />
            <line
              x1={padding + tileSize}
              y1={padding + tileSize / 2}
              x2={padding + tileSize - overlapOffset}
              y2={padding + tileSize / 2}
              stroke="#ef4444"
              strokeWidth="2"
              markerEnd="url(#arrowhead)"
            />
          </>
        )}

        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#ef4444" />
          </marker>
        </defs>
      </svg>

      <div className="mt-3 text-sm text-gray-600">
        <span className="inline-block w-3 h-3 bg-blue-100 border border-blue-500 mr-2 rounded"></span>
        Imaging tiles
        {overlapPercent > 0 && (
          <>
            <span className="mx-2">•</span>
            <span className="text-red-500">←</span> Overlap region
          </>
        )}
      </div>
    </div>
  );
}
