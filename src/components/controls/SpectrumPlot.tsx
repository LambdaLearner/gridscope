import type { SpectrumResult } from '../../api/digitalTwin';

interface SpectrumPlotProps {
  spectrum: SpectrumResult;
  logY?: boolean;
}

const W = 640;
const H = 360;
const PAD = { left: 46, right: 12, top: 16, bottom: 30 };

/**
 * EELS line plot (energy-loss x-axis, log-y by default) with the returned
 * core-loss edges marked as labeled vertical lines. Pure SVG — no chart dep.
 */
export function SpectrumPlot({ spectrum, logY = true }: SpectrumPlotProps) {
  const { energy_ev: E, intensity: I, edges } = spectrum;
  if (E.length === 0 || I.length === 0) return null;

  const y = (v: number) => (logY ? Math.log10(Math.max(v, 1e-6)) : v);
  const ys = I.map(y);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xMin = E[0];
  const xMax = E[E.length - 1];

  const px = (e: number) =>
    PAD.left + ((e - xMin) / Math.max(1e-9, xMax - xMin)) * (W - PAD.left - PAD.right);
  const py = (v: number) =>
    H - PAD.bottom - ((y(v) - yMin) / Math.max(1e-9, yMax - yMin)) * (H - PAD.top - PAD.bottom);

  const path = E.map((e, i) => `${i === 0 ? 'M' : 'L'}${px(e).toFixed(1)},${py(I[i]).toFixed(1)}`).join(' ');

  const xTicks = 5;
  const ticks = Array.from({ length: xTicks + 1 }, (_, i) => xMin + ((xMax - xMin) * i) / xTicks);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-full bg-black"
      role="img"
      aria-label="EELS spectrum"
      data-testid="spectrum-plot"
    >
      {/* axes */}
      <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="#475569" />
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="#475569" />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={px(t)} y1={H - PAD.bottom} x2={px(t)} y2={H - PAD.bottom + 4} stroke="#475569" />
          <text x={px(t)} y={H - PAD.bottom + 16} fill="#64748b" fontSize="10" textAnchor="middle">
            {Math.round(t)}
          </text>
        </g>
      ))}
      <text x={W / 2} y={H - 4} fill="#64748b" fontSize="10" textAnchor="middle">
        energy loss (eV)
      </text>
      <text
        x={12} y={H / 2} fill="#64748b" fontSize="10" textAnchor="middle"
        transform={`rotate(-90 12 ${H / 2})`}
      >
        intensity{logY ? ' (log)' : ''}
      </text>

      {/* core-loss edge markers */}
      {edges.map((edge) => (
        <g key={edge.label} data-testid={`edge-${edge.label}`}>
          <line
            x1={px(edge.onset_ev)} y1={PAD.top} x2={px(edge.onset_ev)} y2={H - PAD.bottom}
            stroke="#f59e0b" strokeDasharray="3 3" opacity={0.7}
          />
          <text x={px(edge.onset_ev) + 3} y={PAD.top + 10} fill="#f59e0b" fontSize="10">
            {edge.label}
          </text>
        </g>
      ))}

      {/* spectrum */}
      <path d={path} fill="none" stroke="#22d3ee" strokeWidth="1.5" />
    </svg>
  );
}
