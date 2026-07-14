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
  setEnvironment,
  resetSpecimen,
  setThickness,
  setDrift,
  setSpecimen,
  type SampleInfo,
} from '../api/simulation';
import { setDetectorSettings, type SessionSnapshot } from '../api/digitalTwin';
import { ApiError } from '../api/client';
import { ParamField } from './controls/ParamField';
import { SeedField } from './controls/SeedField';
import { ScaledSlider } from './controls/ScaledSlider';

interface SampleSettingsPanelProps {
  session: SessionSnapshot | null;
  runActive: boolean;
  onRegistered?: () => void;
}

const ENVIRONMENTS = [
  {
    name: 'pristine',
    description: 'Ideal: no drift, no damage, high dose',
    sets: 'drift ~0 nm/s (excellent) · damage off · contamination off · dwell 20 µs, DQE 0.9',
  },
  {
    name: 'beam_sensitive',
    description: 'Damage accumulates; autofocus can fail',
    sets: 'drift ~0.5 nm/s (good) · damage on (critical dose 1e4 e⁻/Å², rate 0.8) · dwell 10 µs',
  },
  {
    name: 'contaminating',
    description: 'Carbon builds up where the beam dwells',
    sets: 'drift ~1.2 nm/s (moderate) · contamination on (rate 3) · dwell 15 µs',
  },
  {
    name: 'thick_drifting',
    description: 'Strong drift, noisy detector, 90 nm slab',
    sets: 'drift ~5.8 nm/s (poor) · dwell 6 µs, DQE 0.7 · thickness → 90 nm',
  },
  {
    name: 'low_dose',
    description: 'Dose-limited: very noisy imaging, 25 nm slab',
    sets: 'drift ~1.7 nm/s · damage on (5e3, rate 1.0) · dwell 2 µs · thickness → 25 nm',
  },
];

/** Format a dose value like 3.0e4 for the log slider read-out. */
const formatDose = (v: number) => {
  const exp = Math.floor(Math.log10(v));
  return `${(v / 10 ** exp).toFixed(1)}e${exp}`;
};

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
  const [selectedEnv, setSelectedEnv] = useState<string>('pristine');
  const [workingNm, setWorkingNm] = useState(100);
  const [thicknessSeed, setThicknessSeed] = useState(0);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showCustomEnv, setShowCustomEnv] = useState(false);
  const [volumeD, setVolumeD] = useState<number | ''>('');
  const [volumeHW, setVolumeHW] = useState<number | ''>('');
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Custom environment knobs (apply-on-change; override the preset).
  // Drift is in PHYSICAL nm/s (excellent <0.2 · good ~0.5 · moderate ~2 · poor ~5).
  const [driftEnabled, setDriftEnabled] = useState(false);
  const [driftVx, setDriftVx] = useState(0.5);
  const [driftVy, setDriftVy] = useState(0.5);
  const [jitter, setJitter] = useState(0.05);
  const [damageEnabled, setDamageEnabled] = useState(false);
  // Critical dose spans six decades (biological ~1-10 ... metals ~1e5-1e7),
  // so the slider works in log10 space. Default 3e4 = moderately robust.
  const [doseExp, setDoseExp] = useState(Math.log10(3e4));
  const [damageRate, setDamageRate] = useState(1.0);
  const [contamEnabled, setContamEnabled] = useState(false);
  const [contamRate, setContamRate] = useState(1.0);
  const [dwellUs, setDwellUs] = useState(20);

  const connected = session?.connected ?? false;
  const registeredName = session?.sample?.name ?? null;
  const currentEnv = session?.state?.environment;
  const thickness = session?.state?.thickness;
  const busy = isRegistering || runActive;

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
        environment: selectedEnv,
        thickness_nm: workingNm,
        thickness_seed: thicknessSeed,
        ...(volumeD !== '' ? { D: Number(volumeD) } : {}),
        ...(volumeHW !== '' ? { H: Number(volumeHW), W: Number(volumeHW) } : {}),
      });
      const th = result.thickness;
      setNotice(
        `Registered '${result.registered}' (${result.shape.join('×')}) — fresh specimen, ` +
        `environment '${result.environment ?? 'unchanged'}'` +
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

  const handleEnvironmentChange = async (name: string) => {
    setSelectedEnv(name);
    if (!registeredName) return; // applied on register
    setError(null);
    try {
      await setEnvironment(name);
      setNotice(`Environment set to '${name}'`);
      onRegistered?.();
    } catch (e) {
      reportError(e, 'Failed to set environment');
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

  // Custom environment: apply-on-change (overrides the preset). Drift goes
  // through the physical nm/s interface; the server echoes the applied rate.
  const applyDrift = async (patch: Partial<{ enabled: boolean; vx: number; vy: number; jitter: number }>) => {
    try {
      const r = await setDrift({
        enabled: patch.enabled ?? driftEnabled,
        vx_nm_per_s: patch.vx ?? driftVx,
        vy_nm_per_s: patch.vy ?? driftVy,
        line_jitter_nm: patch.jitter ?? jitter,
      });
      setNotice(
        `Drift set: ${r.drift.vx_nm_per_s.toFixed(2)}, ${r.drift.vy_nm_per_s.toFixed(2)} nm/s`,
      );
    } catch (e) {
      reportError(e, 'Failed to set drift');
    }
  };

  const applySpecimen = async (patch: Record<string, unknown>) => {
    try {
      await setSpecimen({
        beam_damage_enabled: (patch.beam_damage_enabled as boolean) ?? damageEnabled,
        damage_dose_threshold: (patch.damage_dose_threshold as number) ?? 10 ** doseExp,
        damage_rate: (patch.damage_rate as number) ?? damageRate,
        contamination_enabled: (patch.contamination_enabled as boolean) ?? contamEnabled,
        contamination_rate: (patch.contamination_rate as number) ?? contamRate,
      });
      setNotice('Custom specimen settings applied');
    } catch (e) {
      reportError(e, 'Failed to set specimen');
    }
  };

  const applyDwell = async (us: number) => {
    try {
      await setDetectorSettings('haadf', { dwell_us: us });
      setNotice(`Dwell time set to ${us} µs`);
    } catch (e) {
      reportError(e, 'Failed to set dwell time');
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
          <span className="font-semibold text-white">Sample Registration &amp; Environment</span>
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
                {currentEnv && <> · environment <span className="font-mono">{currentEnv}</span></>}
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

        {/* ===== Right column: environment ===== */}
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm text-slate-400 flex items-center gap-1">
              <CloudFog className="w-4 h-4" />
              Simulation environment (preset)
            </label>
            <select
              value={selectedEnv}
              onChange={(e) => handleEnvironmentChange(e.target.value)}
              disabled={!connected || busy}
              className="w-full bg-slate-700 text-white text-sm rounded-lg px-3 py-2 border border-slate-600 focus:ring-1 focus:ring-amber-500 disabled:opacity-50"
            >
              {ENVIRONMENTS.map((env) => (
                <option key={env.name} value={env.name}>{env.name}</option>
              ))}
            </select>
            <p className="text-xs text-slate-500">
              {ENVIRONMENTS.find((e) => e.name === selectedEnv)?.description}
            </p>
            <p className="text-[10px] text-slate-600 font-mono leading-relaxed">
              sets: {ENVIRONMENTS.find((e) => e.name === selectedEnv)?.sets}
            </p>
          </div>

          {/* Custom / expert controls (override the preset, apply on change) */}
          <div className="space-y-2">
            <button
              onClick={() => setShowCustomEnv((v) => !v)}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
            >
              {showCustomEnv ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              Custom / expert controls (override preset)
            </button>

            {showCustomEnv && (
              <div className="space-y-4 pl-1">
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
                  <ScaledSlider
                    label="Drift vx" value={driftVx} min={0} max={10} step={0.1} unit="nm/s"
                    scaleLabels={['excellent', 'good', 'moderate', 'poor']}
                    onCommit={(v) => { setDriftVx(v); applyDrift({ vx: v }); }}
                    disabled={!connected || busy || !driftEnabled}
                  />
                  <ScaledSlider
                    label="Drift vy" value={driftVy} min={0} max={10} step={0.1} unit="nm/s"
                    scaleLabels={['excellent', 'good', 'moderate', 'poor']}
                    onCommit={(v) => { setDriftVy(v); applyDrift({ vy: v }); }}
                    disabled={!connected || busy || !driftEnabled}
                  />
                  <ScaledSlider
                    label="Line jitter" value={jitter} min={0} max={0.5} step={0.01} unit="nm"
                    onCommit={(v) => { setJitter(v); applyDrift({ jitter: v }); }}
                    disabled={!connected || busy || !driftEnabled}
                  />
                  <button
                    onClick={() => setDrift({ reset_accum: true }).then(() => setNotice('Drift accumulation reset (view re-centred)')).catch((e) => reportError(e, 'Failed to reset drift'))}
                    disabled={!connected || busy}
                    className="text-[10px] text-slate-400 hover:text-white underline disabled:opacity-50"
                  >
                    Reset accumulated drift (re-centre view)
                  </button>
                </div>

                {/* Beam damage */}
                <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
                  <label className="flex items-center gap-2 text-xs text-slate-300 font-medium">
                    <input
                      type="checkbox"
                      checked={damageEnabled}
                      onChange={(e) => { setDamageEnabled(e.target.checked); applySpecimen({ beam_damage_enabled: e.target.checked }); }}
                      disabled={!connected || busy}
                      className="accent-amber-500"
                    />
                    Beam damage
                  </label>
                  {/* Critical dose spans six decades -> log slider (spec A5) */}
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400">Critical dose</span>
                      <span className="text-white font-mono bg-slate-700 px-2 py-0.5 rounded">
                        {formatDose(10 ** doseExp)} e⁻/Å²
                      </span>
                    </div>
                    <input
                      type="range" min={2} max={6} step={0.05} value={doseExp}
                      onChange={(e) => setDoseExp(Number(e.target.value))}
                      onMouseUp={() => applySpecimen({ damage_dose_threshold: 10 ** doseExp })}
                      onTouchEnd={() => applySpecimen({ damage_dose_threshold: 10 ** doseExp })}
                      disabled={!connected || busy || !damageEnabled}
                      aria-label="Critical dose"
                      className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-amber-500 disabled:opacity-50"
                    />
                    <div className="flex justify-between text-[10px] text-slate-600">
                      <span>zeolite/MOF</span><span>oxides</span><span>metals</span>
                    </div>
                  </div>
                  <ScaledSlider
                    label="Damage rate" value={damageRate} min={0} max={2} step={0.05}
                    onCommit={(v) => { setDamageRate(v); applySpecimen({ damage_rate: v }); }}
                    disabled={!connected || busy || !damageEnabled}
                  />
                </div>

                {/* Contamination */}
                <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
                  <label className="flex items-center gap-2 text-xs text-slate-300 font-medium">
                    <input
                      type="checkbox"
                      checked={contamEnabled}
                      onChange={(e) => { setContamEnabled(e.target.checked); applySpecimen({ contamination_enabled: e.target.checked }); }}
                      disabled={!connected || busy}
                      className="accent-amber-500"
                    />
                    Contamination
                  </label>
                  <ScaledSlider
                    label="Contamination rate" value={contamRate} min={0} max={5} step={0.1}
                    scaleLabels={['none', 'mild', 'heavy']}
                    onCommit={(v) => { setContamRate(v); applySpecimen({ contamination_rate: v }); }}
                    disabled={!connected || busy || !contamEnabled}
                  />
                </div>

                {/* Detector dose */}
                <div className="space-y-2 bg-slate-800/50 rounded-lg p-3">
                  <div className="text-xs text-slate-300 font-medium">Detector dose</div>
                  <ScaledSlider
                    label="Dwell time (lower = noisier)" value={dwellUs} min={1} max={100} step={1} unit="µs"
                    scaleLabels={['noisy', '', 'clean']}
                    onCommit={(v) => { setDwellUs(v); applyDwell(v); }}
                    disabled={!connected || busy}
                  />
                </div>
              </div>
            )}
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
                title="Clear accumulated beam damage and contamination"
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
