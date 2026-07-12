import { Dices } from 'lucide-react';

const MAX_SEED = 2 ** 31 - 1;

interface SeedFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  hint?: string;
}

/**
 * Integer seed input with a randomize button. The resulting number is ALWAYS
 * visible in the field so it can be written down and re-entered — same seed +
 * same parameters reproduces the sample bit-identically.
 */
export function SeedField({ label, value, onChange, disabled, hint }: SeedFieldProps) {
  const randomize = () => onChange(Math.floor(Math.random() * (MAX_SEED + 1)));

  const handleInput = (raw: string) => {
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    onChange(Math.min(MAX_SEED, Math.max(0, Math.floor(n))));
  };

  return (
    <div className="space-y-1">
      <label className="text-xs text-slate-400" title={hint}>{label}</label>
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          min={0}
          max={MAX_SEED}
          step={1}
          value={value}
          onChange={(e) => handleInput(e.target.value)}
          disabled={disabled}
          aria-label={label}
          className="flex-1 min-w-0 bg-slate-700 text-white text-xs font-mono rounded px-2 py-1.5 border border-slate-600 focus:ring-1 focus:ring-amber-500 disabled:opacity-50"
        />
        <button
          type="button"
          onClick={randomize}
          disabled={disabled}
          title={`Randomize ${label.toLowerCase()} (the value stays visible for reproducibility)`}
          aria-label={`Randomize ${label}`}
          className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
        >
          <Dices className="w-3.5 h-3.5 text-amber-400" />
        </button>
      </div>
    </div>
  );
}
