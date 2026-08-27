import { useCallback, useEffect, useState } from 'react';
import {
  FlaskConical,
  Loader2,
  RefreshCw,
  CheckCircle2,
  CloudFog,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Layers,
} from 'lucide-react';
import {
  listSamples,
  registerSample,
  resetSpecimen,
  setThickness,
  setDrift,
  setContamination,
  setNoise,
  setAutofocusLimits,
  type SampleInfo,
} from '../api/simulation';
import type { SessionSnapshot } from '../api/digitalTwin';
import { ApiError } from '../api/client';
import {
  FALLBACK_LIMITS,
  fetchLimits,
  clamp,
  type ConditionLimits,
} from '../api/limits';
import { ParamField } from './controls/ParamField';
import { SeedField } from './controls/SeedField';
import { ScaledSlider } from './controls/ScaledSlider';

interface SampleSettingsPanelProps {
  session: SessionSnapshot | null;
  runActive: boolean;
  onRegistered?: () => void;
}

/** Seed-like params are rendered as SeedField (randomize + visible value). */
const SEED_LABELS: Record<string, string> = {
  seed: 'Structure seed',
  disl_seed: 'Dislocation seed',
};
const isSeedParam = (name: string) => name === 'seed' || name.endsWith('_seed');

export function SampleSettingsPanel({ session, runActive, onRegistered }: SampleSettingsPanelProps) {
  const [samples, setSamples] = useState<SampleInfo[]>([]);
  const [selectedName, setSelectedName] = useState<string>('');
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [workingNm, setWorkingNm] = useState(100);
  const [thicknessSeed, setThicknessSeed] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [volumeD, setVolumeD] = useState<number | ''>('');
  const [volumeHW, setVolumeHW] = useState<number | ''>('');
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Bounds for the free-form condition fields. The backend is the single
  // source of truth (GET /simulation/limits); the fallback covers the gap
  // before the first fetch (or an offline backend).
  const [limits, setLimits] = useState<ConditionLimits>(FALLBACK_LIMITS);

  // Acquisition conditions (apply-on-change). There are no presets: what you
  // set here is exactly what the twin runs with. Drift is in PHYSICAL nm/s
  // (realistic stage drift is 0.1–5 nm/s; anything above is a mechanical
  // fault you are choosing to simulate).
  const [driftEnabled, setDriftEnabled] = useState(false);
  const [driftVx, setDriftVx] = useState(0.5);
  const [driftVy, setDriftVy] = useState(0.5);
  const [jitter, setJitter] = useState(0.05);
  const [maxDtS, setMaxDtS] = useState(2);
  const [contamEnabled, setContamEnabled] = useState(false);
  const [contamRate, setContamRate] = useState(100);
  const [dwellUs, setDwellUs] = useState(20);
  const [dqe, setDqe] = useState(0.8);
  const [readoutE, setReadoutE] = useState(1.5);
  const [doseModel, setDoseModel] = useState(true);
  const [afMinContrast, setAfMinContrast] = useState(0.08);

  const connected = session?.connected ?? false;
  const registeredName = session?.sample?.name ?? null;
  const thickness = session?.state?.thickness;
  const busy = isRegistering || runActive;

  // Fetch the authoritative bounds once per connection.
  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    fetchLimits()
      .then((l) => { if (!cancelled) setLimits(l); })
      .catch(() => { /* keep the offline fallback */ });
    return () => { cancelled = true; };
  }, [connected]);

  // Hydrate the condition widgets from the server on connect and after a
  // registration (hydrating on every 2 s poll would fight in-progress
  // slider edits).
  const stateDrift = session?.state?.drift;
  const stateSpecimen = session?.state?.specimen;
  const stateNoise = session?.state?.detectors?.haadf;
  const stateAutofocus = session?.state?.autofocus;
  useEffect(() => {
    if (stateDrift) {
      setDriftEnabled(stateDrift.enabled >= 0.5);
      setDriftVx(+stateDrift.vx_nm_per_s.toFixed(2));
      setDriftVy(+stateDrift.vy_nm_per_s.toFixed(2));
      if (stateDrift.line_jitter_nm !== undefined) {
        setJitter(+stateDrift.line_jitter_nm.toFixed(2));
      }
      if (stateDrift.max_dt_s !== undefined) setMaxDtS(stateDrift.max_dt_s);
    }
    if (stateSpecimen) {
      setContamEnabled(stateSpecimen.contamination_enabled >= 0.5);
      if (stateSpecimen.contamination_rate !== undefined) {
        setContamRate(stateSpecimen.contamination_rate);
      }
    }
    if (stateNoise) {
      if (stateNoise.dwell_us !== undefined) setDwellUs(stateNoise.dwell_us);
      if (stateNoise.dqe !== undefined) setDqe(stateNoise.dqe);
      if (stateNoise.readout_e !== undefined) setReadoutE(stateNoise.readout_e);
      if (stateNoise.use_dose_model !== undefined) {
        setDoseModel(stateNoise.use_dose_model >= 0.5);
      }
    }
    if (stateAutofocus) setAfMinContrast(stateAutofocus.min_contrast);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, registeredName]);

  const fetchSamples = useCallback(async () => {
    setIsLoadingList(true);
    setError(null);
    try {
      const result = await listSamples();
      setSamples(result.samples);
      setSelectedName((prev) => prev || result.samples[0]?.name || '');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load sample registry');
    } finally {
      setIsLoadingList(false);
    }
  }, []);

  useEffect(() => {
    if (connected && samples.length === 0) fetchSamples();
  }, [connected, samples.length, fetchSamples]);

  const selected = samples.find((s) => s.name === selectedName);

  // Pre-fill controls with the sample's defaults whenever the sample changes.
  useEffect(() => {
    if (selected) setParams({ ...selected.default_params });
  }, [selected?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const reportError = (e: unknown, fallback: string) =>
    setError(e instanceof ApiError ? e.message : `${fallback}: ${e}`);

  const handleRegister = async () => {
    if (!selectedName) return;
    setIsRegistering(true);
    setError(null);
    setNotice(null);
    try {
      const result = await registerSample(selectedName, {
        params,
        thickness_nm: workingNm,
        thickness_seed: thicknessSeed,
        ...(volumeD !== '' ? { D: Number(volumeD) } : {}),
        ...(volumeHW !== '' ? { H: Number(volumeHW), W: Number(volumeHW) } : {}),
      });
      const th = result.thickness;
      setNotice(
        `Registered '${result.registered}' (${result.shape.join('×')}) — fresh specimen` +
        (th
          ? `; images a ${th.working_nm.toFixed(0)} nm slab starting ` +
            `${th.z_start_nm.toFixed(1)} nm into the ${th.total_nm.toFixed(0)} nm specimen`
          : ''),
      );
      onRegistered?.();
    } catch (e) {
      reportError(e, 'Registration failed');
    } finally {
      setIsRegistering(false);
    }
  };

  const handleThicknessCommit = async (nm: number, seed: number) => {
    setError(null);
    if (!registeredName) return; // applied at register time
    try {
      const th = await setThickness({ thickness_nm: nm, thickness_seed: seed });
      setNotice(
        `Images a ${th.working_nm.toFixed(0)} nm slab starting ` +
        `${th.z_start_nm.toFixed(1)} nm into the ${th.total_nm.toFixed(0)} nm specimen`,
      );
      onRegistered?.();
    } catch (e) {
      reportError(e, 'Failed to set thickness');
    }
  };

  const handleResetSpecimen = async () => {
    setError(null);
    try {
      await resetSpecimen();
      setNotice('Specimen degradation history cleared (fresh specimen)');
    } catch (e) {
      reportError(e, 'Failed to reset specimen');
    }
  };

  // Apply-on-change condition setters. Every value is clamped against the
  // server-published bounds before the RPC: the widgets already enforce the
  // range, but a pasted or programmatic value must not bypass it (the twin
  // server itself accepts nearly anything).
  const applyDrift = async (
    patch: Partial<{ enabled: boolean; vx: number; vy: number; jitter: number; maxDt: number }>,
  ) => {
    try {
      const r = await setDrift({
        enabled: patch.enabled ?? driftEnabled,
        vx_nm_per_s: clamp(patch.vx ?? driftVx, limits.drift.vx_nm_per_s),
        vy_nm_per_s: clamp(patch.vy ?? driftVy, limits.drift.vy_nm_per_s),
        line_jitter_nm: clamp(patch.jitter ?? jitter, limits.drift.line_jitter_nm),
        max_dt_s: clamp(patch.maxDt ?? maxDtS, limits.drift.max_dt_s),
      });
      setNotice(
        `Drift set: ${r.drift.vx_nm_per_s.toFixed(2)}, ${r.drift.vy_nm_per_s.toFixed(2)} nm/s`,
      );
    } catch (e) {
      reportError(e, 'Failed to set drift');
    }
  };

  const applyContamination = async (patch: Partial<{ enabled: boolean; rate: number }>) => {
    try {
      const r = await setContamination({
        enabled: patch.enabled ?? contamEnabled,
        rate: clamp(patch.rate ?? contamRate, limits.contamination.rate),
      });
      setNotice(`Contamination: ${r.contamination_enabled >= 0.5 ? 'on' : 'off'}, rate ${r.contamination_rate.toFixed(0)}% of nominal`);
    } catch (e) {
      reportError(e, 'Failed to set contamination');
    }
  };

  const applyNoise = async (
    patch: Partial<{ dwell: number; dqe: number; readout: number; doseModel: boolean }>,
  ) => {
    try {
      await setNoise({
        dwell_us: clamp(patch.dwell ?? dwellUs, limits.noise.dwell_us),
        dqe: clamp(patch.dqe ?? dqe, limits.noise.dqe),
        readout_e: clamp(patch.readout ?? readoutE, limits.noise.readout_e),
        use_dose_model: patch.doseModel ?? doseModel,
      });
      setNotice('Detector noise settings applied');
    } catch (e) {
      reportError(e, 'Failed to set noise');
    }
  };

  const applyAutofocusLimits = async (minContrast: number) => {
    try {
      const r = await setAutofocusLimits({
        min_contrast: clamp(minContrast, limits.autofocus.min_contrast),
      });
      setNotice(`Autofocus min contrast set to ${r.af_min_contrast.toFixed(2)}`);
    } catch (e) {
      reportError(e, 'Failed to set autofocus limits');
    }
  };

  const schemaEntries = Object.entries(selected?.param_schema ?? {});
  const seedEntries = schemaEntries.filter(([k]) => isSeedParam(k));
  const paramEntries = schemaEntries.filter(([k]) => !isSeedParam(k));

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-5 h-5 text-amber-400" />
          <span className="font-semibold text-white">Sample Registration &amp; Conditions</span>
          <span className="text-[10px] text-slate-500 uppercase tracking-wider bg-slate-700 px-1.5 py-0.5 rounded">
            simulation only
          </span>
        </div>
        <button
          onClick={fetchSamples}
          disabled={!connected || isLoadingList}
          className="p-1.5 hover:bg-slate-700 rounded-md transition-colors disabled:opacity-50"
          title="Refresh sample registry"
        >
          <RefreshCw className={`w-4 h-4 text-slate-400 ${isLoadingList ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* ===== Left column: sample + params + seeds + thickness ===== */}
        <div className="space-y-4">
          {registeredName ? (
            <div className="flex items-center gap-2 text-xs bg-emerald-900/20 border border-emerald-900/50 text-emerald-300 rounded-lg px-3 py-2">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              <span>
                Registered: <span className="font-mono">{registeredName}</span>
              </span>
            </div>
          ) : (
            <div className="text-xs bg-amber-900/20 border border-amber-900/50 text-amber-300 rounded-lg px-3 py-2">
              No sample registered — configure one below and register it to enable the microscope.
            </div>
          )}

          {/* Sample picker */}
          <div className="space-y-2">
            <label className="text-sm text-slate-400">Sample ({samples.length} available)</label>
            <select
              value={selectedName}
              onChange={(e) => setSelectedName(e.target.value)}
              disabled={!connected || busy || samples.length === 0}
              className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:ring-1 focus:ring-amber-500 disabled:opacity-50"
            >
              {samples.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.display_name || s.name}
                </option>
              ))}
            </select>
            {selected && (
              <p className="text-xs text-slate-500 leading-relaxed">{selected.description}</p>
            )}
          </div>

          {/* Schema-driven parameters */}
          {paramEntries.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs text-slate-500 uppercase tracking-wider">Parameters</div>
              <div className="grid grid-cols-2 gap-2">
                {paramEntries.map(([name, schema]) => (
                  <ParamField
                    key={`${selectedName}.${name}`}
                    name={name}
                    schema={schema}
                    value={params[name]}
                    onChange={(v) => setParams((p) => ({ ...p, [name]: v }))}
                    disabled={!connected || busy}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Seeds (reproducibility: same seed + params => identical sample) */}
          {seedEntries.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {seedEntries.map(([name]) => (
                <SeedField
                  key={`${selectedName}.${name}`}
                  label={SEED_LABELS[name] ?? name.replace(/_/g, ' ')}
                  value={Number(params[name] ?? 0)}
                  onChange={(v) => setParams((p) => ({ ...p, [name]: v }))}
                  disabled={!connected || busy}
                  hint="Same seed + same parameters reproduces the sample bit-identically"
                />
              ))}
            </div>
          )}

          {/* Thickness workflow */}
          <div className="space-y-2 pt-2 border-t border-slate-700">
            <div className="text-xs text-slate-500 uppercase tracking-wider flex items-center gap-1">
              <Layers className="w-3.5 h-3.5" />
              Specimen thickness
            </div>
            <ScaledSlider
              label="Working thickness (slab the beam passes through)"
              value={workingNm}
              min={1}
              max={100}
              step={1}
              unit="nm"
              scaleLabels={['thin', '', 'thick']}
              onCommit={(v) => { setWorkingNm(v); handleThicknessCommit(v, thicknessSeed); }}
              disabled={!connected || busy}
            />
            <div className="grid grid-cols-2 gap-2 items-end">
              <SeedField
                label="Thickness seed"
                value={thicknessSeed}
                onChange={(v) => { setThicknessSeed(v); handleThicknessCommit(workingNm, v); }}
                disabled={!connected || busy}
                hint="Decides WHERE in the 100 nm specimen the working slab sits"
              />
              {thickness && (
                <div className="text-[11px] text-slate-500 leading-snug pb-1" data-testid="z-window-readout">
                  images a {thickness.working_nm.toFixed(0)} nm slab starting{' '}
                  {thickness.z_start_nm.toFixed(1)} nm into the {thickness.total_nm.toFixed(0)} nm specimen
                </div>
              )}
            </div>
          </div>

          {/* Advanced: volume resolution */}
          <div className="space-y-2">
            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
            >
              {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              Advanced: volume resolution
            </button>
            {showAdvanced && (
              <div className="grid grid-cols-2 gap-2 pl-4">
                <div className="space-y-0.5">
                  <label className="text-xs text-slate-400">Depth D (max 128)</label>
                  <input
                    type="number"
                    min={12}
                    max={128}
                    placeholder="default"
                    value={volumeD}
                    onChange={(e) => setVolumeD(e.target.value === '' ? '' : Number(e.target.value))}
                    disabled={!connected || busy}
                    className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1.5 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <div className="space-y-0.5">
                  <label className="text-xs text-slate-400">H = W (max 1024)</label>
                  <input
                    type="number"
                    min={32}
                    max={1024}
                    placeholder="default"
                    value={volumeHW}
                    onChange={(e) => setVolumeHW(e.target.value === '' ? '' : Number(e.target.value))}
                    disabled={!connected || busy}
                    className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1.5 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <p className="col-span-2 text-[10px] text-slate-600">
                  Larger volumes take longer to generate.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ===== Right column: acquisition conditions ===== */}
        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm text-slate-400 flex items-center gap-1">
              <CloudFog className="w-4 h-4" />
              Acquisition conditions
            </label>
            <p className="text-xs text-slate-500 leading-relaxed">
              No presets: the values below are exactly what the twin runs
              with. They apply on change and are independent of sample
              registration.
            </p>
          </div>

          <div className="space-y-4">
            {/* Drift */}
            <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
              <label className="flex items-center gap-2 text-xs text-slate-300 font-medium">
                <input
                  type="checkbox"
                  checked={driftEnabled}
                  onChange={(e) => { setDriftEnabled(e.target.checked); applyDrift({ enabled: e.target.checked }); }}
                  disabled={!connected || busy}
                  className="accent-amber-500"
                />
                Mechanical drift
              </label>
              {/* Visibility depends on FOV: 1 px ≈ FOV/1024, so at a 20 µm
                  field even 10 nm/s moves <1 px per frame. Watch drift in
                  Live mode at ≤1 µm FOV, or raise the rate. */}
              <ScaledSlider
                label="Drift vx" value={driftVx} min={limits.drift.vx_nm_per_s.min} max={limits.drift.vx_nm_per_s.max} step={0.1} unit="nm/s"
                scaleLabels={['excellent', 'good', 'moderate', 'poor']}
                onCommit={(v) => { setDriftVx(v); applyDrift({ vx: v }); }}
                disabled={!connected || busy || !driftEnabled}
              />
              <ScaledSlider
                label="Drift vy" value={driftVy} min={limits.drift.vy_nm_per_s.min} max={limits.drift.vy_nm_per_s.max} step={0.1} unit="nm/s"
                scaleLabels={['excellent', 'good', 'moderate', 'poor']}
                onCommit={(v) => { setDriftVy(v); applyDrift({ vy: v }); }}
                disabled={!connected || busy || !driftEnabled}
              />
              <ScaledSlider
                label="Line jitter" value={jitter} min={limits.drift.line_jitter_nm.min} max={limits.drift.line_jitter_nm.max} step={0.05} unit="nm"
                onCommit={(v) => { setJitter(v); applyDrift({ jitter: v }); }}
                disabled={!connected || busy || !driftEnabled}
              />
              <ScaledSlider
                label="Idle-time cap (drift accrual per frame)" value={maxDtS} min={limits.drift.max_dt_s.min} max={limits.drift.max_dt_s.max} step={1} unit="s"
                onCommit={(v) => { setMaxDtS(v); applyDrift({ maxDt: v }); }}
                disabled={!connected || busy || !driftEnabled}
              />
              <p className="text-[10px] text-slate-500 leading-snug">
                Drift shows as frame-to-frame motion: use Live mode at a small
                FOV (≤1 µm) — at wide fields one pixel spans tens of nm, so
                even fast drift looks static. The idle-time cap keeps a long
                pause from teleporting the field; raise it to let a deliberate
                wait accumulate.
              </p>
              <button
                onClick={() => setDrift({ reset_accum: true }).then(() => setNotice('Drift accumulation reset (view re-centred)')).catch((e) => reportError(e, 'Failed to reset drift'))}
                disabled={!connected || busy}
                className="text-[10px] text-slate-400 hover:text-white underline disabled:opacity-50"
              >
                Reset accumulated drift (re-centre view)
              </button>
            </div>

            {/* Contamination */}
            <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
              <label className="flex items-center gap-2 text-xs text-slate-300 font-medium">
                <input
                  type="checkbox"
                  checked={contamEnabled}
                  onChange={(e) => { setContamEnabled(e.target.checked); applyContamination({ enabled: e.target.checked }); }}
                  disabled={!connected || busy}
                  className="accent-amber-500"
                />
                Contamination
              </label>
              <ScaledSlider
                label="Rate (% of nominal; 100 = calibrated rate)" value={contamRate} min={limits.contamination.rate.min} max={limits.contamination.rate.max} step={10} unit="%"
                scaleLabels={['off', 'nominal', 'fast']}
                onCommit={(v) => { setContamRate(v); applyContamination({ rate: v }); }}
                disabled={!connected || busy || !contamEnabled}
              />
              <p className="text-[10px] text-slate-500 leading-snug">
                Contamination builds where the beam dwells: it needs repeated
                frames over the same spot (Live mode at high magnification)
                and grows fastest with high current and long dwell.
              </p>
            </div>

            {/* Detector noise / dose */}
            <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-300 font-medium">Detector noise &amp; dose</div>
              {/* Deliberate practical subrange of the served bound (0.1–1000):
                  1–100 µs is where real dwell lives; the clamp still allows a
                  blob/script to use the full served range. */}
              <ScaledSlider
                label="Dwell time (lower = noisier)" value={dwellUs} min={1} max={100} step={1} unit="µs"
                scaleLabels={['noisy', '', 'clean']}
                onCommit={(v) => { setDwellUs(v); applyNoise({ dwell: v }); }}
                disabled={!connected || busy}
              />
              <ScaledSlider
                label="DQE (detector quantum efficiency)" value={dqe} min={limits.noise.dqe.min} max={limits.noise.dqe.max} step={0.01}
                onCommit={(v) => { setDqe(v); applyNoise({ dqe: v }); }}
                disabled={!connected || busy}
              />
              <ScaledSlider
                label="Readout noise" value={readoutE} min={limits.noise.readout_e.min} max={10} step={0.1} unit="e⁻"
                onCommit={(v) => { setReadoutE(v); applyNoise({ readout: v }); }}
                disabled={!connected || busy}
              />
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={doseModel}
                  onChange={(e) => { setDoseModel(e.target.checked); applyNoise({ doseModel: e.target.checked }); }}
                  disabled={!connected || busy}
                  className="accent-amber-500"
                />
                Poisson dose model (off = legacy gaussian noise)
              </label>
            </div>

            {/* Autofocus acceptance */}
            <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-300 font-medium">Autofocus</div>
              <ScaledSlider
                label="Min contrast for convergence (higher = stricter)"
                value={afMinContrast} min={limits.autofocus.min_contrast.min} max={limits.autofocus.min_contrast.max} step={0.01}
                onCommit={(v) => { setAfMinContrast(v); applyAutofocusLimits(v); }}
                disabled={!connected || busy}
              />
              <p className="text-[10px] text-slate-500 leading-snug">
                Autofocus reports non-convergence when its sharpness curve's
                peak/floor ratio falls below this — raise it to make focus
                failure easier to trigger in workflow tests.
              </p>
            </div>
          </div>

          {/* Register + reset */}
          <div className="flex gap-2 pt-2">
            <button
              onClick={handleRegister}
              disabled={!connected || busy || !selectedName}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 bg-amber-600 hover:bg-amber-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors text-sm font-medium"
            >
              {isRegistering ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Building volume...
                </>
              ) : (
                <>
                  <FlaskConical className="w-4 h-4" />
                  {registeredName ? 'Register new sample' : 'Register / Load sample'}
                </>
              )}
            </button>
            {registeredName && (
              <button
                onClick={handleResetSpecimen}
                disabled={!connected || busy}
                className="flex items-center gap-1 px-3 py-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-300 rounded-lg transition-colors text-xs"
                title="Clear accumulated contamination"
              >
                <RotateCcw className="w-3 h-3" />
                Fresh specimen
              </button>
            )}
          </div>

          {runActive && (
            <p className="text-xs text-slate-500">
              Sample settings are locked while a script run is in progress.
            </p>
          )}

          {notice && !error && (
            <div className="text-emerald-400 text-xs py-2 px-3 bg-emerald-900/20 rounded-lg border border-emerald-900/50">
              {notice}
            </div>
          )}
          {error && (
            <div className="text-red-400 text-xs py-2 px-3 bg-red-900/20 rounded-lg border border-red-900/50">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
