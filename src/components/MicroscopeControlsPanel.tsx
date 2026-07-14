import { useEffect, useRef, useState } from 'react';
import {
  Camera,
  Download,
  Focus,
  Radio,
  ZoomIn,
  ZoomOut,
  Move,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Loader2,
  Image as ImageIcon,
  Circle,
  RotateCcw,
  RotateCw,
  Rotate3D,
  Scan,
  Sparkles,
  Zap,
  Gauge,
  ShieldAlert,
  Activity,
  Atom,
} from 'lucide-react';
import {
  acquireImage,
  acquireSpectrum,
  captureTiffUrl,
  runAutofocus,
  setStagePosition,
  setDetectorSettings,
  setDiffractionSettings,
  setMode,
  setBeamSettings,
  setResolution,
  type SessionSnapshot,
  type SpectrumResult,
} from '../api/digitalTwin';
import {
  computeAbtemDiffraction,
  getAbtemAvailability,
} from '../api/simulation';
import { ApiError } from '../api/client';
import { LinkedFovMag } from './controls/LinkedFovMag';
import { SpectrumPlot } from './controls/SpectrumPlot';

type ImagingMode = 'IMG' | 'DIFF' | 'EELS';
type DiffEngine = 'kinematical' | 'abtem';

interface MicroscopeControlsPanelProps {
  session: SessionSnapshot | null;
  sampleRegistered: boolean;
  runActive: boolean;
  onAcquired?: () => void;
}

interface PanelError {
  kind: 'limit' | 'busy' | 'error';
  message: string;
}

export function MicroscopeControlsPanel({
  session,
  sampleRegistered,
  runActive,
  onAcquired,
}: MicroscopeControlsPanelProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState('Working...');
  const [currentImage, setCurrentImage] = useState<string | null>(null);
  const [imageInfo, setImageInfo] = useState<{
    x_um: number; y_um: number; fov_um: number; a: number; b: number; mode: string;
  } | null>(null);
  const [error, setError] = useState<PanelError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fov, setFov] = useState(20);
  const [moveStep, setMoveStep] = useState(5);
  const [tiltStep, setTiltStep] = useState(5);
  const [beamCurrent, setBeamCurrent] = useState(80);
  const [beamVoltage, setBeamVoltage] = useState(200);
  // Live mode (spec rev 4): re-acquire continuously; the recommended way to
  // see drift, since the twin advances drift by real elapsed time per frame.
  const [live, setLive] = useState(false);
  const liveRef = useRef(false);
  // EELS
  const [spectrum, setSpectrum] = useState<SpectrumResult | null>(null);
  const [evMin, setEvMin] = useState(0);
  const [evMax, setEvMax] = useState(1000);
  const [nChannels, setNChannels] = useState(1024);
  // Diffraction engine (kinematical = server; abTEM = decoupled dynamical path)
  const [diffEngine, setDiffEngine] = useState<DiffEngine>('kinematical');
  const [abtemAvailable, setAbtemAvailable] = useState<boolean | null>(null);
  const [frozenPhonons, setFrozenPhonons] = useState(0);
  const [abtemMeta, setAbtemMeta] = useState<string | null>(null);
  // Kinematical diffraction settings
  const [apertureUm, setApertureUm] = useState(0.4);
  const [depthNm, setDepthNm] = useState(20);
  const [cameraLengthMm, setCameraLengthMm] = useState(800);
  const [beamstopPx, setBeamstopPx] = useState(6);

  const connected = session?.connected ?? false;
  const state = session?.state;
  const limits = state?.stage_limits;
  const imagingMode = (state?.mode as ImagingMode) ?? 'IMG';
  const tiltA = state?.stage?.a ?? 0;
  const tiltB = state?.stage?.b ?? 0;
  const tiltLimit = limits?.a ?? 30;
  const resolutionPx = state?.resolution?.resolution_px ?? 512;
  const allowedResolutions = state?.resolution?.allowed ?? [512, 1024, 2048];
  const controlsEnabled = connected && sampleRegistered && !runActive && !isLoading;

  // Grey out the abTEM toggle when the optional dependency is missing (501).
  useEffect(() => {
    if (!connected || abtemAvailable !== null) return;
    getAbtemAvailability()
      .then((r) => setAbtemAvailable(r.available))
      .catch(() => setAbtemAvailable(false));
  }, [connected, abtemAvailable]);

  // Live loop: adaptive cadence — the next acquire starts only after the
  // previous frame returns (never overlapping calls), floored at ~300 ms.
  useEffect(() => {
    liveRef.current = live;
    if (!live) return;
    let cancelled = false;
    (async () => {
      while (!cancelled && liveRef.current) {
        const t0 = performance.now();
        try {
          const result = await acquireImage('haadf');
          if (cancelled || !liveRef.current) break;
          setCurrentImage(`data:image/png;base64,${result.image.image_base64}`);
          setAbtemMeta(null);
          setImageInfo({
            x_um: result.stage.x_um, y_um: result.stage.y_um,
            fov_um: result.settings?.field_of_view_um ?? fov,
            a: result.stage.a, b: result.stage.b, mode: result.mode,
          });
        } catch {
          setLive(false);
          break;
        }
        const elapsed = performance.now() - t0;
        await new Promise((r) => setTimeout(r, Math.max(300 - elapsed, 0)));
      }
      onAcquired?.();
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  // Live only makes sense for image modes while the instrument is available.
  useEffect(() => {
    if (live && (imagingMode === 'EELS' || !connected || !sampleRegistered || runActive)) {
      setLive(false);
    }
  }, [live, imagingMode, connected, sampleRegistered, runActive]);

  const classifyError = (e: unknown, fallback: string): PanelError => {
    if (e instanceof ApiError) {
      if (e.isSafetyLimitRejection) return { kind: 'limit', message: e.message };
      if (e.isConflict) return { kind: 'busy', message: e.message };
      return { kind: 'error', message: e.message };
    }
    return { kind: 'error', message: fallback };
  };

  const runAction = async (label: string, action: () => Promise<void>, fallback: string) => {
    setIsLoading(true);
    setLoadingLabel(label);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (e) {
      setError(classifyError(e, fallback));
    } finally {
      setIsLoading(false);
    }
  };

  const doAcquire = async () => {
    if (imagingMode === 'EELS') {
      const result = await acquireSpectrum({ ev_min: evMin, ev_max: evMax, n_channels: nChannels });
      setSpectrum(result);
      onAcquired?.();
      return;
    }
    const result = await acquireImage('haadf');
    setCurrentImage(`data:image/png;base64,${result.image.image_base64}`);
    setAbtemMeta(null); // viewer now shows a server (kinematical) frame
    setImageInfo({
      x_um: result.stage.x_um,
      y_um: result.stage.y_um,
      fov_um: result.settings?.field_of_view_um ?? fov,
      a: result.stage.a,
      b: result.stage.b,
      mode: result.mode,
    });
    onAcquired?.();
  };

  const handleAcquire = () =>
    runAction(
      imagingMode === 'EELS'
        ? 'Acquiring spectrum...'
        : imagingMode === 'DIFF'
          ? 'Computing diffraction (may take a few seconds)...'
          : resolutionPx >= 2048
            ? 'Acquiring (2048 px, ~30 s)...'
            : 'Acquiring...',
      doAcquire,
      'Failed to acquire',
    );

  // abTEM path: explicit compute button (seconds to tens of seconds), never
  // auto-refresh. Stage tilt is applied to the atoms server-side in the
  // FastAPI process — NOT by the twin (this path is decoupled from it).
  const handleComputeAbtem = () =>
    runAction('Computing dynamical pattern (abTEM)...', async () => {
      const r = await computeAbtemDiffraction({ num_frozen_phonons: frozenPhonons });
      setCurrentImage(`data:image/png;base64,${r.image.image_base64}`);
      setImageInfo({
        x_um: 0, y_um: 0, fov_um: fov,
        a: r.state.tilt_a_deg, b: r.state.tilt_b_deg, mode: 'DIFF',
      });
      setAbtemMeta(
        `abTEM · ${r.n_atoms.toLocaleString()} atoms · ${r.state.energy_kev.toFixed(0)} kV` +
        (r.state.num_frozen_phonons ? ` · ${r.state.num_frozen_phonons} phonon configs` : '') +
        (r.cached ? ' · cached' : ` · ${r.compute_seconds}s`),
      );
    }, 'Dynamical computation failed');

  const handleDiffractionSettingsCommit = () =>
    runAction('Applying diffraction settings...', async () => {
      await setDiffractionSettings({
        aperture_um: apertureUm,
        depth_nm: depthNm,
        camera_length_mm: cameraLengthMm,
        beamstop_radius_px: beamstopPx,
      });
      await doAcquire();
    }, 'Failed to apply diffraction settings');

  const handleResolutionChange = (px: number) => {
    if (px === resolutionPx) return;
    return runAction(`Setting resolution to ${px} px...`, async () => {
      await setResolution(px);
      onAcquired?.();
    }, 'Failed to set resolution');
  };

  const handleAutofocus = () =>
    runAction('Autofocusing...', async () => {
      const af = await runAutofocus('haadf', 6.0, 13);
      if (af.result.converged) {
        setNotice(`Autofocus converged: Z adjusted by ${af.result.best_z_um_relative.toFixed(2)} µm`);
        await doAcquire();
      } else {
        // Legitimate failure mode: the stage was NOT moved.
        setError({
          kind: 'error',
          message: `Autofocus did not converge — ${af.result.reason}. Focus unchanged.`,
        });
      }
    }, 'Autofocus failed');

  // While Live is running, movement handlers skip their own re-acquire —
  // the live loop picks up the new position on its next frame.
  const handleMove = (dxUm: number, dyUm: number) =>
    runAction('Moving stage...', async () => {
      await setStagePosition({ x: dxUm * 1e-6, y: dyUm * 1e-6 }, true);
      if (!liveRef.current) await doAcquire();
    }, 'Failed to move stage');

  const handleTilt = (da: number, db: number) =>
    runAction('Tilting...', async () => {
      await setStagePosition({ a: tiltA + da, b: tiltB + db }, false);
      if (!liveRef.current) await doAcquire();
    }, 'Failed to set tilt');

  const handleResetTilt = () =>
    runAction('Resetting tilt...', async () => {
      await setStagePosition({ a: 0, b: 0 }, false);
      if (!liveRef.current) await doAcquire();
    }, 'Failed to reset tilt');

  // z focus nudge (spec A1): fine steps change focus/PSF; coarse navigates.
  const handleFocus = (dzUm: number) =>
    runAction('Adjusting focus (z)...', async () => {
      await setStagePosition({ z: dzUm * 1e-6 }, true);
      if (!liveRef.current) await doAcquire();
    }, 'Failed to adjust focus');

  const handleSaveTiff = () => {
    // The backend stashes the most-recent raw frame; this streams it as a
    // 32-bit float TIFF download with embedded acquisition metadata.
    const a = document.createElement('a');
    a.href = captureTiffUrl();
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const handleFovChange = (newFov: number) => {
    setFov(newFov);
    return runAction('Setting field of view...', async () => {
      await setDetectorSettings('haadf', { field_of_view_um: newFov });
      await doAcquire();
    }, 'Failed to change FOV');
  };

  const handleModeChange = (mode: ImagingMode) => {
    if (mode === imagingMode) return;
    return runAction('Switching mode...', async () => {
      await setMode(mode);
      // Refresh the viewer for image modes; EELS waits for an explicit acquire.
      if (mode !== 'EELS') {
        const result = await acquireImage('haadf');
        setCurrentImage(`data:image/png;base64,${result.image.image_base64}`);
        setAbtemMeta(null);
      }
      onAcquired?.();
    }, 'Failed to change mode');
  };

  const handleBeamChange = (current: number, voltage: number) =>
    runAction('Updating beam...', async () => {
      await setBeamSettings({ current_pA: current, voltage_kV: voltage });
      await doAcquire();
    }, 'Failed to update beam settings');

  const magnification = state?.detectors?.haadf?.magnification;

  // FOV range: 100 nm to 50 µm. Below 5 µm the ±5 µm buttons would be
  // useless, so zoom steps halve/double there instead.
  const FOV_MIN_UM = 0.1;
  const FOV_MAX_UM = 50;
  const zoomInFov = () =>
    handleFovChange(Math.max(FOV_MIN_UM, fov > 5 ? fov - 5 : +(fov / 2).toFixed(2)));
  const zoomOutFov = () =>
    handleFovChange(Math.min(FOV_MAX_UM, fov < 5 ? +(fov * 2).toFixed(2) : fov + 5));
  const formatFov = (value: number) =>
    value < 1 ? `${Math.round(value * 1000)} nm` : `${value} µm`;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <Scan className="w-5 h-5 text-cyan-400" />
          <span className="font-semibold text-white">Microscope Controls</span>
          <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
        </div>
        {limits && (
          <span
            className="text-[10px] text-slate-500 font-mono"
            title="Stage soft limits (moves beyond these are rejected)"
          >
            limits ±{(limits.x * 1e3).toFixed(1)}mm xy · ±{(limits.z * 1e3).toFixed(1)}mm z · ±{limits.a}°
          </span>
        )}
      </div>

      {/* Gate banner */}
      {connected && !sampleRegistered && (
        <div className="px-4 py-2 bg-amber-900/20 border-b border-amber-900/50 text-amber-300 text-xs">
          Register a sample in Sample Settings to enable the microscope.
        </div>
      )}
      {runActive && (
        <div className="px-4 py-2 bg-violet-900/20 border-b border-violet-900/50 text-violet-300 text-xs">
          Script run in progress — controls are read-only until it finishes.
        </div>
      )}

      {/* Mode toggle */}
      <div className="p-3 bg-slate-800/50 border-b border-slate-700">
        <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Mode</div>
        <div className="flex rounded-lg overflow-hidden border border-slate-600">
          <button
            onClick={() => handleModeChange('IMG')}
            disabled={!controlsEnabled}
            className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
              imagingMode === 'IMG' ? 'bg-cyan-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            <ImageIcon className="w-3 h-3" />
            Imaging
          </button>
          <button
            onClick={() => handleModeChange('DIFF')}
            disabled={!controlsEnabled}
            className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
              imagingMode === 'DIFF' ? 'bg-violet-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            <Sparkles className="w-3 h-3" />
            Diffraction
          </button>
          <button
            onClick={() => handleModeChange('EELS')}
            disabled={!controlsEnabled}
            className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
              imagingMode === 'EELS' ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            <Activity className="w-3 h-3" />
            EELS
          </button>
        </div>
      </div>

      {/* Viewer (image / diffraction / EELS line plot) */}
      <div className="relative aspect-square bg-black flex items-center justify-center">
        {imagingMode === 'EELS' && spectrum ? (
          <SpectrumPlot spectrum={spectrum} />
        ) : imagingMode !== 'EELS' && currentImage ? (
          <img src={currentImage} alt="Microscope view" className="w-full h-full object-contain" />
        ) : (
          <div className="text-center text-slate-600">
            {imagingMode === 'EELS' ? (
              <Activity className="w-16 h-16 mx-auto mb-2 opacity-30" />
            ) : (
              <ImageIcon className="w-16 h-16 mx-auto mb-2 opacity-30" />
            )}
            <p className="text-sm">{imagingMode === 'EELS' ? 'No spectrum acquired' : 'No image acquired'}</p>
            <p className="text-xs mt-1 text-slate-700">
              {sampleRegistered ? 'Click Acquire to capture' : 'Register a sample first'}
            </p>
          </div>
        )}

        {currentImage && (
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-cyan-500/30" />
            <div className="absolute top-1/2 left-0 right-0 h-px bg-cyan-500/30" />
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
              <Circle className="w-8 h-8 text-cyan-500/50" strokeWidth={1} />
            </div>
          </div>
        )}

        {imageInfo && (
          <div className="absolute bottom-2 left-2 bg-black/80 text-white text-xs px-2 py-1 rounded font-mono">
            ({imageInfo.x_um.toFixed(1)}, {imageInfo.y_um.toFixed(1)}) µm • FOV: {imageInfo.fov_um.toFixed(1)} µm
            {` • α=${imageInfo.a.toFixed(1)}° β=${imageInfo.b.toFixed(1)}°`}
          </div>
        )}

        <div
          className={`absolute top-2 right-2 text-white text-xs px-2 py-1 rounded-full flex items-center gap-1 ${
            imagingMode === 'DIFF' ? 'bg-violet-600/90' : imagingMode === 'EELS' ? 'bg-emerald-600/90' : 'bg-cyan-600/90'
          }`}
        >
          {imagingMode === 'DIFF' ? <Sparkles className="w-3 h-3" /> : imagingMode === 'EELS' ? <Activity className="w-3 h-3" /> : <ImageIcon className="w-3 h-3" />}
          {imagingMode === 'DIFF' ? (abtemMeta ? 'Diffraction (abTEM)' : 'Diffraction') : imagingMode === 'EELS' ? 'EELS' : 'Imaging'}
        </div>

        {abtemMeta && imagingMode === 'DIFF' && (
          <div className="absolute bottom-8 left-2 bg-violet-900/80 text-violet-200 text-[10px] px-2 py-1 rounded font-mono">
            {abtemMeta}
          </div>
        )}

        {session?.sample?.name && (
          <div className="absolute top-2 left-2 bg-amber-600/90 text-white text-xs px-2 py-1 rounded-full font-mono">
            {session.sample.name}
          </div>
        )}

        {live && (
          <div className="absolute top-10 right-2 bg-red-600/90 text-white text-[10px] px-2 py-0.5 rounded-full flex items-center gap-1 font-semibold tracking-wider">
            <Radio className="w-3 h-3 animate-pulse" />
            LIVE
          </div>
        )}

        {isLoading && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <div className="flex items-center gap-2 text-cyan-400">
              <Loader2 className="w-6 h-6 animate-spin" />
              <span className="text-sm">{loadingLabel}</span>
            </div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="p-4 space-y-4 bg-slate-800/50">
        <div className="flex gap-2">
          <button
            onClick={handleAcquire}
            disabled={!controlsEnabled || live}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 bg-cyan-600 hover:bg-cyan-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors text-sm font-medium"
          >
            <Camera className="w-4 h-4" />
            Acquire
          </button>
          {imagingMode !== 'EELS' && (
            <button
              onClick={() => setLive((v) => !v)}
              disabled={!connected || !sampleRegistered || runActive}
              title="Continuously re-acquire (~300 ms cadence, never overlapping). The recommended way to watch drift."
              className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg transition-colors text-sm font-medium ${
                live
                  ? 'bg-red-600 hover:bg-red-700 text-white'
                  : 'bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:bg-slate-700 disabled:text-slate-500'
              }`}
            >
              <Radio className={`w-4 h-4 ${live ? 'animate-pulse' : ''}`} />
              {live ? 'Stop live' : 'Live'}
            </button>
          )}
          <button
            onClick={handleAutofocus}
            disabled={!controlsEnabled || live}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors text-sm font-medium"
          >
            <Focus className="w-4 h-4" />
            Autofocus
          </button>
          <button
            onClick={handleSaveTiff}
            disabled={!connected || (!currentImage && !abtemMeta)}
            title="Download the most-recent frame as a 32-bit float TIFF with embedded acquisition metadata"
            className="flex items-center justify-center gap-2 px-3 py-2.5 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-700 disabled:text-slate-500 text-slate-200 rounded-lg transition-colors text-sm"
          >
            <Download className="w-4 h-4" />
            TIFF
          </button>
        </div>

        {/* Dose meter (spec A5): accumulated dose vs the critical dose */}
        {state?.specimen &&
          (state.specimen.beam_damage_enabled >= 0.5 ||
            state.specimen.contamination_enabled >= 0.5) && (
          <div className="text-[11px] text-slate-400 bg-slate-900/60 rounded-lg px-3 py-2 font-mono flex items-center gap-3"
               data-testid="dose-meter">
            <span className="text-amber-400">dose</span>
            <span>
              {state.specimen.max_accumulated_dose.toExponential(1)} e⁻/Å²
              {state.specimen.beam_damage_enabled >= 0.5 && (
                <> / critical {state.specimen.damage_dose_threshold.toExponential(1)}</>
              )}
            </span>
            {state.specimen.beam_damage_enabled >= 0.5 && (
              <div className="flex-1 h-1.5 bg-slate-700 rounded overflow-hidden">
                <div
                  className={`h-full ${
                    state.specimen.max_accumulated_dose >= state.specimen.damage_dose_threshold
                      ? 'bg-red-500' : 'bg-amber-500'
                  }`}
                  style={{
                    width: `${Math.min(100,
                      (state.specimen.max_accumulated_dose /
                        Math.max(1, state.specimen.damage_dose_threshold)) * 100)}%`,
                  }}
                />
              </div>
            )}
          </div>
        )}

        {/* Resolution windows (discrete, like a real scan generator) */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <Scan className="w-4 h-4" />
              Resolution
            </span>
            <span className="text-[10px] text-slate-600">higher = finer detail, slower frame</span>
          </div>
          <div className="flex rounded-lg overflow-hidden border border-slate-600">
            {allowedResolutions.map((px) => (
              <button
                key={px}
                onClick={() => handleResolutionChange(px)}
                disabled={!controlsEnabled}
                title={px >= 1024 ? `${px} px (slower${px >= 2048 ? ', ~30 s/frame' : ''})` : `${px} px`}
                className={`flex-1 px-2 py-1.5 text-xs font-mono transition-colors ${
                  resolutionPx === px ? 'bg-cyan-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                }`}
              >
                {px}{px >= 1024 ? '·slow' : ''}
              </button>
            ))}
          </div>
        </div>

        {/* FOV / magnification (linked pair: two views of one quantity) */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <ZoomIn className="w-4 h-4" />
              Field of View / Magnification
            </span>
            <span className="text-white font-mono text-xs bg-slate-700 px-2 py-0.5 rounded">
              {formatFov(fov)}
              {magnification ? ` · ${(magnification / 1e3).toFixed(1)} kx` : ''}
            </span>
          </div>
          <LinkedFovMag
            fovUm={state?.detectors?.haadf?.field_of_view_um ?? fov}
            onCommit={(v) => handleFovChange(v)}
            disabled={!controlsEnabled}
          />
          <div className="flex items-center gap-2">
            <button
              onClick={zoomInFov}
              disabled={!controlsEnabled}
              title="Zoom in (smaller field of view)"
              className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
            >
              <ZoomIn className="w-4 h-4 text-white" />
            </button>
            <input
              type="range"
              min={FOV_MIN_UM}
              max={FOV_MAX_UM}
              step={FOV_MIN_UM}
              value={fov}
              onChange={(e) => setFov(Number(e.target.value))}
              onMouseUp={() => handleFovChange(fov)}
              onTouchEnd={() => handleFovChange(fov)}
              disabled={!controlsEnabled}
              className="flex-1 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-500 disabled:opacity-50"
            />
            <button
              onClick={zoomOutFov}
              disabled={!controlsEnabled}
              title="Zoom out (larger field of view)"
              className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
            >
              <ZoomOut className="w-4 h-4 text-white" />
            </button>
          </div>
        </div>

        {/* Stage controls */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <Move className="w-4 h-4" />
              Stage Control
            </span>
            <select
              value={moveStep}
              onChange={(e) => setMoveStep(Number(e.target.value))}
              disabled={!controlsEnabled}
              className="bg-slate-700 text-white text-xs rounded px-2 py-1 border-none focus:ring-1 focus:ring-cyan-500 disabled:opacity-50"
            >
              <option value={0.1}>100 nm</option>
              <option value={0.5}>500 nm</option>
              <option value={1}>1 µm</option>
              <option value={5}>5 µm</option>
              <option value={10}>10 µm</option>
              <option value={20}>20 µm</option>
            </select>
          </div>

          <div className="flex justify-center">
            <div className="grid grid-cols-3 gap-1">
              <div />
              <button onClick={() => handleMove(0, -moveStep)} disabled={!controlsEnabled} className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors">
                <ArrowUp className="w-4 h-4 text-white" />
              </button>
              <div />
              <button onClick={() => handleMove(-moveStep, 0)} disabled={!controlsEnabled} className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors">
                <ArrowLeft className="w-4 h-4 text-white" />
              </button>
              <button onClick={handleAcquire} disabled={!controlsEnabled} className="p-2.5 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 rounded transition-colors">
                <Circle className="w-4 h-4 text-white" />
              </button>
              <button onClick={() => handleMove(moveStep, 0)} disabled={!controlsEnabled} className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors">
                <ArrowRight className="w-4 h-4 text-white" />
              </button>
              <div />
              <button onClick={() => handleMove(0, moveStep)} disabled={!controlsEnabled} className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors">
                <ArrowDown className="w-4 h-4 text-white" />
              </button>
              <div />
            </div>
          </div>
        </div>

        {/* Focus (z) — spec A1: value always displayed; fine steps change the
            PSF (manual focus companion to Autofocus), coarse steps navigate. */}
        <div className="space-y-2 pt-2 border-t border-slate-700">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <Focus className="w-4 h-4" />
              Focus (z)
              <span className="text-[10px] text-slate-600">(fine ±5 µm · hard ±1000 µm)</span>
            </span>
            <span
              className="text-xs text-cyan-300 font-mono bg-slate-700 px-2 py-0.5 rounded"
              data-testid="z-readout"
            >
              z = {((state?.stage?.z ?? 0) * 1e6) >= 0 ? '+' : ''}
              {((state?.stage?.z ?? 0) * 1e6).toFixed(2)} µm
            </span>
          </div>
          <div className="grid grid-cols-4 gap-1.5">
            <button
              onClick={() => handleFocus(-25)}
              disabled={!controlsEnabled}
              title="Coarse focus −25 µm"
              className="px-2 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded text-xs text-white font-mono transition-colors"
            >
              −25
            </button>
            <button
              onClick={() => handleFocus(-0.25)}
              disabled={!controlsEnabled}
              title="Fine focus −0.25 µm"
              className="px-2 py-1.5 bg-slate-700 hover:bg-cyan-700 disabled:opacity-50 rounded text-xs text-white font-mono transition-colors"
            >
              −0.25
            </button>
            <button
              onClick={() => handleFocus(0.25)}
              disabled={!controlsEnabled}
              title="Fine focus +0.25 µm"
              className="px-2 py-1.5 bg-slate-700 hover:bg-cyan-700 disabled:opacity-50 rounded text-xs text-white font-mono transition-colors"
            >
              +0.25
            </button>
            <button
              onClick={() => handleFocus(25)}
              disabled={!controlsEnabled}
              title="Coarse focus +25 µm"
              className="px-2 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded text-xs text-white font-mono transition-colors"
            >
              +25
            </button>
          </div>
        </div>

        {/* Tilt controls */}
        <div className="space-y-2 pt-2 border-t border-slate-700">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <Rotate3D className="w-4 h-4" />
              Tilt Control
              <span className="text-[10px] text-slate-600">(±{tiltLimit}°)</span>
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-violet-400 font-mono bg-slate-700 px-2 py-0.5 rounded">
                α={tiltA.toFixed(1)}° β={tiltB.toFixed(1)}°
              </span>
              <button
                onClick={handleResetTilt}
                disabled={!controlsEnabled || (tiltA === 0 && tiltB === 0)}
                className="text-xs text-slate-400 hover:text-white disabled:opacity-50 px-1"
                title="Reset tilt to 0°"
              >
                Reset
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={tiltStep}
              onChange={(e) => setTiltStep(Number(e.target.value))}
              disabled={!controlsEnabled}
              className="bg-slate-700 text-white text-xs rounded px-2 py-1 border-none focus:ring-1 focus:ring-violet-500 disabled:opacity-50"
            >
              <option value={1}>1°</option>
              <option value={5}>5°</option>
              <option value={10}>10°</option>
              <option value={15}>15°</option>
            </select>

            <div className="flex-1 grid grid-cols-2 gap-2">
              <div className="flex items-center gap-1">
                <span className="text-xs text-slate-500 w-4">α</span>
                <button onClick={() => handleTilt(-tiltStep, 0)} disabled={!controlsEnabled} className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center" title={`Tilt α -${tiltStep}°`}>
                  <RotateCcw className="w-3 h-3 text-white" />
                </button>
                <button onClick={() => handleTilt(tiltStep, 0)} disabled={!controlsEnabled} className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center" title={`Tilt α +${tiltStep}°`}>
                  <RotateCw className="w-3 h-3 text-white" />
                </button>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-xs text-slate-500 w-4">β</span>
                <button onClick={() => handleTilt(0, -tiltStep)} disabled={!controlsEnabled} className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center" title={`Tilt β -${tiltStep}°`}>
                  <RotateCcw className="w-3 h-3 text-white" />
                </button>
                <button onClick={() => handleTilt(0, tiltStep)} disabled={!controlsEnabled} className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center" title={`Tilt β +${tiltStep}°`}>
                  <RotateCw className="w-3 h-3 text-white" />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Diffraction controls + engine toggle (DIFF mode only) */}
        {imagingMode === 'DIFF' && (
          <div className="space-y-3 pt-2 border-t border-slate-700">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400 flex items-center gap-1">
                <Sparkles className="w-4 h-4" />
                Diffraction engine
              </span>
              <div className="flex rounded-lg overflow-hidden border border-slate-600">
                <button
                  onClick={() => setDiffEngine('kinematical')}
                  className={`px-2 py-1 text-xs transition-colors ${
                    diffEngine === 'kinematical' ? 'bg-violet-600 text-white' : 'bg-slate-700 text-slate-400'
                  }`}
                >
                  Kinematical
                </button>
                <button
                  onClick={() => abtemAvailable && setDiffEngine('abtem')}
                  disabled={!abtemAvailable}
                  title={
                    abtemAvailable
                      ? 'Dynamical multislice (slow, analysis-grade). Stage tilt is applied to the atoms by the backend — this path is decoupled from the twin server.'
                      : 'abTEM is not installed on the backend (pip install abtem)'
                  }
                  className={`px-2 py-1 text-xs transition-colors flex items-center gap-1 ${
                    diffEngine === 'abtem'
                      ? 'bg-violet-600 text-white'
                      : abtemAvailable
                        ? 'bg-slate-700 text-slate-400'
                        : 'bg-slate-800 text-slate-600 cursor-not-allowed'
                  }`}
                >
                  <Atom className="w-3 h-3" />
                  abTEM
                </button>
              </div>
            </div>

            {diffEngine === 'abtem' ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-slate-400 flex-1">Frozen phonons (0–16, slower)</label>
                  <input
                    type="number"
                    min={0}
                    max={16}
                    step={1}
                    value={frozenPhonons}
                    onChange={(e) => setFrozenPhonons(Math.min(16, Math.max(0, Math.round(Number(e.target.value) || 0))))}
                    disabled={!controlsEnabled}
                    aria-label="Frozen phonons"
                    className="w-16 bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <button
                  onClick={handleComputeAbtem}
                  disabled={!controlsEnabled}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-violet-600 hover:bg-violet-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors text-xs font-medium"
                >
                  <Atom className="w-3.5 h-3.5" />
                  Compute dynamical pattern
                </button>
                <p className="text-[10px] text-slate-600 leading-snug">
                  Takes seconds to tens of seconds; results are cached per state.
                  Stage α/β are applied to the atoms by the backend (decoupled from the server).
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-0.5">
                  <label className="text-xs text-slate-400">Aperture (µm)</label>
                  <input
                    type="number" min={0} max={100} step={0.1} value={apertureUm}
                    onChange={(e) => setApertureUm(Number(e.target.value))}
                    disabled={!controlsEnabled}
                    aria-label="Aperture (µm)"
                    className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <div className="space-y-0.5">
                  <label className="text-xs text-slate-400">Depth (nm)</label>
                  <input
                    type="number" min={0} max={1000} step={1} value={depthNm}
                    onChange={(e) => setDepthNm(Number(e.target.value))}
                    disabled={!controlsEnabled}
                    aria-label="Depth (nm)"
                    className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <div className="space-y-0.5">
                  <label className="text-xs text-slate-400">Camera length (mm)</label>
                  <input
                    type="number" min={100} max={10000} step={50} value={cameraLengthMm}
                    onChange={(e) => setCameraLengthMm(Number(e.target.value))}
                    disabled={!controlsEnabled}
                    aria-label="Camera length (mm)"
                    className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <div className="space-y-0.5">
                  <label className="text-xs text-slate-400">Beamstop (px)</label>
                  <input
                    type="number" min={0} max={64} step={1} value={beamstopPx}
                    onChange={(e) => setBeamstopPx(Number(e.target.value))}
                    disabled={!controlsEnabled}
                    aria-label="Beamstop (px)"
                    className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                  />
                </div>
                <button
                  onClick={handleDiffractionSettingsCommit}
                  disabled={!controlsEnabled}
                  className="col-span-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg transition-colors text-xs"
                >
                  Apply &amp; re-acquire
                </button>
              </div>
            )}
          </div>
        )}

        {/* EELS controls (EELS mode only) */}
        {imagingMode === 'EELS' && (
          <div className="space-y-2 pt-2 border-t border-slate-700">
            <div className="text-sm text-slate-400 flex items-center gap-1">
              <Activity className="w-4 h-4" />
              EELS acquisition
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-0.5">
                <label className="text-xs text-slate-400">eV min</label>
                <input
                  type="number" min={0} max={5000} step={10} value={evMin}
                  onChange={(e) => setEvMin(Number(e.target.value))}
                  disabled={!controlsEnabled}
                  aria-label="EELS eV min"
                  className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                />
              </div>
              <div className="space-y-0.5">
                <label className="text-xs text-slate-400">eV max</label>
                <input
                  type="number" min={10} max={5000} step={10} value={evMax}
                  onChange={(e) => setEvMax(Number(e.target.value))}
                  disabled={!controlsEnabled}
                  aria-label="EELS eV max"
                  className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                />
              </div>
              <div className="space-y-0.5">
                <label className="text-xs text-slate-400">Channels</label>
                <input
                  type="number" min={16} max={8192} step={16} value={nChannels}
                  onChange={(e) => setNChannels(Number(e.target.value))}
                  disabled={!controlsEnabled}
                  aria-label="EELS channels"
                  className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1 border border-slate-600 disabled:opacity-50"
                />
              </div>
            </div>
            <p className="text-[10px] text-slate-600 leading-snug">
              Single-spot spectrum (probe parked at one position). The twin's spectrum is a
              physically-structured dummy — edges reflect the elements under the probe.
            </p>
          </div>
        )}

        {/* Beam controls */}
        <div className="space-y-3 pt-2 border-t border-slate-700">
          <div className="text-sm text-slate-400 flex items-center gap-1">
            <Zap className="w-4 h-4" />
            Beam Settings
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 flex items-center gap-1">
                <Zap className="w-3 h-3 text-yellow-400" />
                Voltage
              </span>
              <select
                value={beamVoltage}
                onChange={(e) => {
                  const kv = Number(e.target.value);
                  setBeamVoltage(kv);
                  handleBeamChange(beamCurrent, kv);
                }}
                disabled={!controlsEnabled}
                aria-label="Accelerating voltage"
                className="bg-slate-700 text-yellow-400 font-mono text-xs rounded px-2 py-1 border-none focus:ring-1 focus:ring-yellow-500 disabled:opacity-50"
              >
                {[60, 80, 120, 200, 300].map((kv) => (
                  <option key={kv} value={kv}>{kv} kV</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 flex items-center gap-1">
                <Gauge className="w-3 h-3 text-orange-400" />
                Current
              </span>
              <span className="text-orange-400 font-mono bg-slate-700 px-2 py-0.5 rounded">{beamCurrent} pA</span>
            </div>
            <input
              type="range"
              min="1"
              max="500"
              step="1"
              value={beamCurrent}
              onChange={(e) => setBeamCurrent(Number(e.target.value))}
              onMouseUp={() => handleBeamChange(beamCurrent, beamVoltage)}
              onTouchEnd={() => handleBeamChange(beamCurrent, beamVoltage)}
              disabled={!controlsEnabled}
              className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-orange-500 disabled:opacity-50"
            />
            <div className="flex justify-between text-[10px] text-slate-600">
              <span>noisy (dose-limited)</span><span>clean</span>
            </div>
          </div>
        </div>

        {/* Notices and errors */}
        {notice && !error && (
          <div className="text-emerald-400 text-xs text-center py-2 bg-emerald-900/20 rounded-lg border border-emerald-900/50">
            {notice}
          </div>
        )}
        {error && (
          <div
            className={`text-xs py-2 px-3 rounded-lg border flex items-start gap-2 ${
              error.kind === 'limit'
                ? 'text-amber-300 bg-amber-900/20 border-amber-900/50'
                : error.kind === 'busy'
                  ? 'text-violet-300 bg-violet-900/20 border-violet-900/50'
                  : 'text-red-400 bg-red-900/20 border-red-900/50'
            }`}
          >
            {error.kind === 'limit' && <ShieldAlert className="w-4 h-4 flex-shrink-0 mt-0.5" />}
            <span>{error.message}</span>
          </div>
        )}
      </div>
    </div>
  );
}
