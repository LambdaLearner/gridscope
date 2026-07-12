import { useEffect, useState } from 'react';
import { fovUmToMag, magToFovUm } from '../../api/digitalTwin';

interface LinkedFovMagProps {
  /** Current field of view in µm (source of truth from the session). */
  fovUm: number;
  /** Called with the new FOV (µm) when either field is committed. */
  onCommit: (fovUm: number) => void;
  disabled?: boolean;
  minFovUm?: number;
  maxFovUm?: number;
}

/**
 * FOV and magnification are two views of the same quantity
 * (mag = MAG_K / fov_metres). Editing either field live-updates the other;
 * committing (Enter / blur) applies the value. Spec §2.4.
 */
export function LinkedFovMag({
  fovUm, onCommit, disabled, minFovUm = 0.005, maxFovUm = 100,
}: LinkedFovMagProps) {
  const [fovText, setFovText] = useState(fovUm.toFixed(3));
  const [magText, setMagText] = useState((fovUmToMag(fovUm) / 1e3).toFixed(1));

  useEffect(() => {
    setFovText(fovUm >= 1 ? fovUm.toFixed(2) : fovUm.toFixed(3));
    setMagText((fovUmToMag(fovUm) / 1e3).toFixed(1));
  }, [fovUm]);

  const clampFov = (v: number) => Math.min(maxFovUm, Math.max(minFovUm, v));

  const handleFovInput = (text: string) => {
    setFovText(text);
    const v = Number(text);
    if (Number.isFinite(v) && v > 0) setMagText((fovUmToMag(v) / 1e3).toFixed(1));
  };

  const handleMagInput = (text: string) => {
    setMagText(text);
    const kx = Number(text);
    if (Number.isFinite(kx) && kx > 0) {
      const v = magToFovUm(kx * 1e3);
      setFovText(v >= 1 ? v.toFixed(2) : v.toFixed(3));
    }
  };

  const commitFov = () => {
    const v = Number(fovText);
    if (Number.isFinite(v) && v > 0) onCommit(clampFov(v));
  };

  const commitMag = () => {
    const kx = Number(magText);
    if (Number.isFinite(kx) && kx > 0) onCommit(clampFov(magToFovUm(kx * 1e3)));
  };

  const onEnter = (commit: () => void) => (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') commit();
  };

  return (
    <div className="grid grid-cols-2 gap-2">
      <div className="space-y-0.5">
        <label className="text-xs text-slate-400">FOV (µm)</label>
        <input
          type="number"
          value={fovText}
          min={minFovUm}
          max={maxFovUm}
          step="any"
          onChange={(e) => handleFovInput(e.target.value)}
          onBlur={commitFov}
          onKeyDown={onEnter(commitFov)}
          disabled={disabled}
          aria-label="Field of view (µm)"
          className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1.5 border border-slate-600 focus:ring-1 focus:ring-cyan-500 disabled:opacity-50"
        />
      </div>
      <div className="space-y-0.5">
        <label className="text-xs text-slate-400">Magnification (kx)</label>
        <input
          type="number"
          value={magText}
          min={1}
          step="any"
          onChange={(e) => handleMagInput(e.target.value)}
          onBlur={commitMag}
          onKeyDown={onEnter(commitMag)}
          disabled={disabled}
          aria-label="Magnification (kx)"
          className="w-full bg-slate-700 text-white text-xs font-mono rounded px-2 py-1.5 border border-slate-600 focus:ring-1 focus:ring-cyan-500 disabled:opacity-50"
        />
      </div>
    </div>
  );
}
