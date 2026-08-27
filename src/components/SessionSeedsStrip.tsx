import { useState } from 'react';
import { Copy, Check, Upload, Fingerprint } from 'lucide-react';
import {
  getCurrentSample,
  registerSample,
  setDrift,
  setContamination,
  setNoise,
  setAutofocusLimits,
} from '../api/simulation';
import type { SessionSnapshot } from '../api/digitalTwin';
import { clamp, FALLBACK_LIMITS } from '../api/limits';

interface SessionSeedsStripProps {
  session: SessionSnapshot | null;
  disabled?: boolean;
  onApplied?: () => void;
}

/** v2 blob: explicit acquisition-condition values replace the v1 preset
 *  name — a restored session reproduces the exact numbers, not a label. */
interface SeedBlob {
  version: 2;
  sample: string;
  params: Record<string, unknown>;
  thickness_nm: number;
  thickness_seed: number;
  conditions: {
    drift: {
      enabled: boolean;
      vx_nm_per_s: number;
      vy_nm_per_s: number;
      line_jitter_nm: number;
      max_dt_s: number;
    };
    contamination: { enabled: boolean; rate: number };
    noise: { dwell_us: number; dqe: number; readout_e: number; use_dose_model: boolean };
    autofocus: { min_contrast: number };
  };
}

/**
 * Always-visible reproducibility read-out (spec §3.1): structure seed(s),
 * thickness seed + z-window, acquisition conditions. Copy dumps the exact
 * state as JSON; Load re-applies a pasted blob so a state can be shared or
 * revisited.
 */
export function SessionSeedsStrip({ session, disabled, onApplied }: SessionSeedsStripProps) {
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const state = session?.state;
  const sampleName = session?.sample?.name;
  const thickness = state?.thickness;
  const drift = state?.drift;
  const specimen = state?.specimen;

  const handleCopy = async () => {
    if (!sampleName) return;
    setStatus(null);
    try {
      const current = await getCurrentSample();
      const haadf = state?.detectors?.haadf;
      const blob: SeedBlob = {
        version: 2,
        sample: sampleName,
        params: current.sample.params ?? {},
        thickness_nm: thickness?.working_nm ?? 100,
        thickness_seed: thickness?.seed ?? 0,
        conditions: {
          drift: {
            enabled: (drift?.enabled ?? 0) >= 0.5,
            vx_nm_per_s: drift?.vx_nm_per_s ?? 0,
            vy_nm_per_s: drift?.vy_nm_per_s ?? 0,
            line_jitter_nm: drift?.line_jitter_nm ?? 0,
            max_dt_s: drift?.max_dt_s ?? 2,
          },
          contamination: {
            enabled: (specimen?.contamination_enabled ?? 0) >= 0.5,
            rate: specimen?.contamination_rate ?? 100,
          },
          noise: {
            dwell_us: haadf?.dwell_us ?? 20,
            dqe: haadf?.dqe ?? 0.8,
            readout_e: haadf?.readout_e ?? 1.5,
            use_dose_model: (haadf?.use_dose_model ?? 1) >= 0.5,
          },
          autofocus: { min_contrast: state?.autofocus?.min_contrast ?? 0.08 },
        },
      };
      await navigator.clipboard.writeText(JSON.stringify(blob, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      setStatus(`Copy failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  const handleLoad = async () => {
    setStatus(null);
    const text = window.prompt('Paste a session-seeds JSON blob to re-apply that exact state:');
    if (!text) return;
    setApplying(true);
    try {
      const blob = JSON.parse(text) as SeedBlob & { environment?: string };
      if (!blob.sample) throw new Error('blob has no "sample" field');
      if (blob.version !== 2) {
        throw new Error(
          blob.environment !== undefined
            ? 'this is a preset-era (v1) blob — environment presets no longer exist; copy a fresh blob'
            : 'unsupported blob version — copy a fresh blob',
        );
      }
      await registerSample(blob.sample, {
        params: blob.params ?? {},
        thickness_nm: blob.thickness_nm,
        thickness_seed: blob.thickness_seed,
      });
      // A pasted blob is free-form text — clamp every numeric condition so a
      // hand-edited value cannot bypass the widget bounds (the routes would
      // 422 it, but that would abort the restore half-applied).
      const c = blob.conditions;
      const L = FALLBACK_LIMITS;
      await setDrift({
        enabled: c.drift.enabled,
        vx_nm_per_s: clamp(c.drift.vx_nm_per_s, L.drift.vx_nm_per_s),
        vy_nm_per_s: clamp(c.drift.vy_nm_per_s, L.drift.vy_nm_per_s),
        line_jitter_nm: clamp(c.drift.line_jitter_nm, L.drift.line_jitter_nm),
        max_dt_s: clamp(c.drift.max_dt_s, L.drift.max_dt_s),
        reset_accum: true,
      });
      await setContamination({
        enabled: c.contamination.enabled,
        rate: clamp(c.contamination.rate, L.contamination.rate),
      });
      await setNoise({
        dwell_us: clamp(c.noise.dwell_us, L.noise.dwell_us),
        dqe: clamp(c.noise.dqe, L.noise.dqe),
        readout_e: clamp(c.noise.readout_e, L.noise.readout_e),
        use_dose_model: c.noise.use_dose_model,
      });
      await setAutofocusLimits({
        min_contrast: clamp(c.autofocus.min_contrast, L.autofocus.min_contrast),
      });
      setStatus(`Re-applied '${blob.sample}' exactly (seeds + thickness + conditions)`);
      onApplied?.();
    } catch (e) {
      setStatus(`Load failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setApplying(false);
    }
  };

  const driftChip = drift && drift.enabled >= 0.5
    ? `drift ${drift.vx_nm_per_s.toFixed(1)}/${drift.vy_nm_per_s.toFixed(1)} nm/s`
    : 'drift off';
  const contamChip = specimen && specimen.contamination_enabled >= 0.5
    ? `contam ${specimen.contamination_rate.toFixed(0)}%`
    : 'contam off';

  return (
    <div className="flex items-center gap-3 px-4 py-1.5 bg-slate-900/70 border-b border-slate-800 text-[11px] text-slate-500">
      <span className="flex items-center gap-1 text-slate-400">
        <Fingerprint className="w-3.5 h-3.5 text-amber-500" />
        Session seeds
      </span>
      {sampleName ? (
        <>
          <span className="font-mono">{sampleName}</span>
          {thickness && (
            <span className="font-mono" data-testid="seeds-thickness">
              t={thickness.working_nm.toFixed(0)}nm · seed {thickness.seed} · z₀={thickness.z_start_nm.toFixed(1)}nm
            </span>
          )}
          <span className="font-mono" data-testid="seeds-conditions">
            {driftChip} · {contamChip}
          </span>
        </>
      ) : (
        <span className="italic">no sample registered</span>
      )}
      <div className="flex-1" />
      {status && <span className="text-amber-400 truncate max-w-md">{status}</span>}
      <button
        onClick={handleCopy}
        disabled={disabled || !sampleName}
        title="Copy the exact state (sample, params/seeds, thickness, conditions) as JSON"
        className="flex items-center gap-1 px-2 py-0.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 rounded transition-colors"
      >
        {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
        Copy
      </button>
      <button
        onClick={handleLoad}
        disabled={disabled || applying}
        title="Paste a copied blob to re-apply that exact state"
        className="flex items-center gap-1 px-2 py-0.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 rounded transition-colors"
      >
        <Upload className="w-3 h-3" />
        {applying ? 'Applying…' : 'Load'}
      </button>
    </div>
  );
}
