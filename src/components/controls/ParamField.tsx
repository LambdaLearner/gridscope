import type { ParamSchemaEntry } from '../../api/simulation';

interface ParamFieldProps {
  name: string;
  schema: ParamSchemaEntry;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}

/**
 * Generic schema-driven control for one sample parameter (spec §1.2: do NOT
 * hard-code parameter controls). Renders by schema type:
 *   int   -> bounded integer spinbox
 *   float -> bounded float spinbox (step ~ (max-min)/100)
 *   bool  -> checkbox
 *   str   -> text field
 */
export function ParamField({ name, schema, value, onChange, disabled }: ParamFieldProps) {
  const label = name.replace(/_/g, ' ');
  const range =
    schema.min !== undefined && schema.max !== undefined
      ? `${schema.min}–${schema.max}`
      : undefined;

  if (schema.type === 'bool') {
    return (
      <label className="flex items-center gap-2 text-xs text-slate-300 py-1">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          disabled={disabled}
          aria-label={name}
          className="accent-amber-500"
        />
        {label}
      </label>
    );
  }

  if (schema.type === 'str') {
    return (
      <div className="space-y-0.5">
        <label className="text-xs text-slate-400">{label}</label>
        <input
          type="text"
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          aria-label={name}
          className="w-full bg-slate-700 text-white text-xs rounded px-2 py-1.5 border border-slate-600 focus:ring-1 focus:ring-amber-500 disabled:opacity-50"
        />
      </div>
    );
  }

  // int / float
  const isInt = schema.type === 'int';
  const step = isInt
    ? 1
    : schema.min !== undefined && schema.max !== undefined
      ? Math.max((schema.max - schema.min) / 100, 1e-6)
      : 0.1;

  const clamp = (n: number) => {
    let v = n;
    if (schema.min !== undefined) v = Math.max(schema.min, v);
    if (schema.max !== undefined) v = Math.min(schema.max, v);
    return isInt ? Math.round(v) : v;
  };

  return (
    <div className="space-y-0.5">
      <label className="text-xs text-slate-400">
        {label}
        {range && <span className="text-slate-600"> ({range})</span>}
      </label>
      <input
        type="number"
        value={value === undefined || value === null ? '' : Number(value)}
        min={schema.min}
        max={schema.max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(clamp(n));
        }}
        disabled={disabled}
        aria-label={name}
        className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1.5 border border-slate-600 focus:ring-1 focus:ring-amber-500 disabled:opacity-50"
      />
    </div>
  );
}
