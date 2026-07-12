import { useState } from 'react';
import { Copy, Check, Upload, Fingerprint } from 'lucide-react';
import { getCurrentSample, registerSample, setEnvironment } from '../api/simulation';
import type { SessionSnapshot } from '../api/digitalTwin';

interface SessionSeedsStripProps {
  session: SessionSnapshot | null;
  disabled?: boolean;
  onApplied?: () => void;
}

interface SeedBlob {
  sample: string;
  params: Record<string, unknown>;
  thickness_nm: number;
  thickness_seed: number;
  environment: string;
}

/**
 * Always-visible reproducibility read-out (spec §3.1): structure seed(s),
 * thickness seed + z-window, environment. Copy dumps the exact state as JSON;
 * Load re-applies a pasted blob so a state can be shared or revisited.
 */
export function SessionSeedsStrip({ session, disabled, onApplied }: SessionSeedsStripProps) {
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const state = session?.state;
  const sampleName = session?.sample?.name;
  const thickness = state?.thickness;
  const environment = state?.environment;

  const handleCopy = async () => {
    if (!sampleName) return;
    setStatus(null);
    try {
      const current = await getCurrentSample();
      const blob: SeedBlob = {
        sample: sampleName,
        params: current.sample.params ?? {},
        thickness_nm: thickness?.working_nm ?? 100,
        thickness_seed: thickness?.seed ?? 0,
        environment: environment ?? 'pristine',
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
      const blob = JSON.parse(text) as SeedBlob;
      if (!blob.sample) throw new Error('blob has no "sample" field');
      await registerSample(blob.sample, {
        params: blob.params ?? {},
        thickness_nm: blob.thickness_nm,
        thickness_seed: blob.thickness_seed,
      });
      if (blob.environment) await setEnvironment(blob.environment);
      setStatus(`Re-applied '${blob.sample}' exactly (seeds + thickness + environment)`);
      onApplied?.();
    } catch (e) {
      setStatus(`Load failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setApplying(false);
    }
  };

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
          {environment && <span className="font-mono">env: {environment}</span>}
        </>
      ) : (
        <span className="italic">no sample registered</span>
      )}
      <div className="flex-1" />
      {status && <span className="text-amber-400 truncate max-w-md">{status}</span>}
      <button
        onClick={handleCopy}
        disabled={disabled || !sampleName}
        title="Copy the exact state (sample, params/seeds, thickness, environment) as JSON"
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
