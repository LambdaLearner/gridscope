import { useEffect, useState } from 'react';

interface ScaledSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  /** Qualitative scale labels rendered under the track, e.g. none/mild/moderate/severe. */
  scaleLabels?: string[];
  /** Called on release (debounced apply), not on every tick. */
  onCommit: (value: number) => void;
  disabled?: boolean;
  accent?: string;
}

/**
 * Slider with a live value readout and optional qualitative scale labels, so
 * users without a feel for the units still get intuitive control. Commits on
 * release, never on every tick (the twin call may be expensive).
 */
export function ScaledSlider({
  label, value, min, max, step = (max - min) / 100, unit = '',
  scaleLabels, onCommit, disabled, accent = 'accent-amber-500',
}: ScaledSliderProps) {
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-white font-mono bg-slate-700 px-2 py-0.5 rounded">
          {Number.isInteger(step) ? local : local.toFixed(2)}{unit ? ` ${unit}` : ''}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        onChange={(e) => setLocal(Number(e.target.value))}
        onMouseUp={() => onCommit(local)}
        onTouchEnd={() => onCommit(local)}
        onKeyUp={(e) => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') onCommit(local); }}
        disabled={disabled}
        aria-label={label}
        className={`w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer ${accent} disabled:opacity-50`}
      />
      {scaleLabels && scaleLabels.length > 1 && (
        <div className="flex justify-between text-[10px] text-slate-600">
          {scaleLabels.map((s) => <span key={s}>{s}</span>)}
        </div>
      )}
    </div>
  );
}
