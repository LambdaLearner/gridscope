import { useCallback, useEffect, useState } from 'react';
import {
  FlaskConical,
  Loader2,
  RefreshCw,
  CheckCircle2,
  CloudFog,
  RotateCcw,
} from 'lucide-react';
import {
  listSamples,
  registerSample,
  setEnvironment,
  resetSpecimen,
  type SampleInfo,
} from '../api/simulation';
import { ApiError } from '../api/client';
import type { SessionSnapshot } from '../api/digitalTwin';

interface SampleSettingsPanelProps {
  session: SessionSnapshot | null;
  runActive: boolean;
  onRegistered?: () => void;
}

const ENVIRONMENTS = [
  { name: 'pristine', description: 'Ideal: no drift, no damage, high dose' },
  { name: 'beam_sensitive', description: 'Damage accumulates; autofocus can fail' },
  { name: 'contaminating', description: 'Carbon builds up where the beam dwells' },
  { name: 'thick_drifting', description: 'Strong drift, noisy detector' },
  { name: 'low_dose', description: 'Dose-limited: very noisy imaging' },
];

export function SampleSettingsPanel({ session, runActive, onRegistered }: SampleSettingsPanelProps) {
  const [samples, setSamples] = useState<SampleInfo[]>([]);
  const [selectedName, setSelectedName] = useState<string>('');
  const [selectedEnv, setSelectedEnv] = useState<string>('pristine');
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const connected = session?.connected ?? false;
  const registeredName = session?.sample?.name ?? null;
  const currentEnv = session?.state?.environment;
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

  const handleRegister = async () => {
    if (!selectedName) return;
    setIsRegistering(true);
    setError(null);
    setNotice(null);
    try {
      const result = await registerSample(selectedName, {}, selectedEnv);
      setNotice(
        `Registered '${result.registered}' (${result.shape.join('×')}) — fresh specimen, ` +
        `environment '${result.environment ?? 'unchanged'}'`,
      );
      onRegistered?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Registration failed: ${e}`);
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
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Failed to set environment: ${e}`);
    }
  };

  const handleResetSpecimen = async () => {
    setError(null);
    try {
      await resetSpecimen();
      setNotice('Specimen degradation history cleared (fresh specimen)');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Failed to reset specimen: ${e}`);
    }
  };

  const selected = samples.find((s) => s.name === selectedName);

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-5 h-5 text-amber-400" />
          <span className="font-semibold text-white">Sample Settings</span>
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

      <div className="p-4 space-y-4">
        {/* Registration status */}
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
            No sample registered — pick one below and register it to enable the microscope.
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

        {/* Environment picker */}
        <div className="space-y-2">
          <label className="text-sm text-slate-400 flex items-center gap-1">
            <CloudFog className="w-4 h-4" />
            Simulation environment
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
        </div>

        {/* Actions */}
        <div className="flex gap-2">
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
                {registeredName ? 'Register new sample' : 'Register sample'}
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
  );
}
