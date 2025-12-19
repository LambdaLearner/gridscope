import { useState, useEffect } from 'react';
import { 
  Camera, 
  RefreshCw, 
  Focus, 
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
  Atom,
  Sparkles,
  Zap,
  Gauge
} from 'lucide-react';
import {
  getMicroscopeStatus,
  acquireImage,
  runAutofocus,
  setStagePosition,
  setDetectorSettings,
  setMode,
  setSampleType,
  setBeamSettings,
  type MicroscopeState,
  type AcquireResult,
} from '../api/digitalTwin';

interface MicroscopeViewerProps {
  onStateChange?: (state: MicroscopeState) => void;
  onImageAcquired?: (result: AcquireResult) => void;
}

export function MicroscopeViewer({ onStateChange, onImageAcquired }: MicroscopeViewerProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [state, setState] = useState<MicroscopeState | null>(null);
  const [currentImage, setCurrentImage] = useState<string | null>(null);
  const [imageInfo, setImageInfo] = useState<{ x_um: number; y_um: number; fov_um: number; a?: number; b?: number; mode?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fov, setFov] = useState(20);
  const [moveStep, setMoveStep] = useState(5);
  const [tiltA, setTiltA] = useState(0);
  const [tiltB, setTiltB] = useState(0);
  const [tiltStep, setTiltStep] = useState(5);
  const [is3DMode, setIs3DMode] = useState(true);
  
  // New state for STEM features
  const [imagingMode, setImagingMode] = useState<'IMG' | 'DIFF'>('IMG');
  const [sampleType, setSampleTypeState] = useState<'au_nanoparticles' | 'fcc_crystal'>('au_nanoparticles');
  
  // Beam settings
  const [beamCurrent, setBeamCurrent] = useState(50);  // pA
  const [beamVoltage, setBeamVoltage] = useState(200); // kV

  useEffect(() => {
    checkConnection();
  }, []);

  const checkConnection = async () => {
    try {
      const status = await getMicroscopeStatus();
      setIsConnected(status.connected);
      if (status.state) {
        setState(status.state);
        onStateChange?.(status.state);
        if (status.state.detectors?.haadf) {
          setFov(status.state.detectors.haadf.field_of_view_um);
        }
        // Get tilt state
        if (status.state.stage) {
          setTiltA(status.state.stage.a || 0);
          setTiltB(status.state.stage.b || 0);
        }
        // Get mode and sample type
        if (status.state.mode) {
          setImagingMode(status.state.mode as 'IMG' | 'DIFF');
        }
        if (status.state.sample_type) {
          setSampleTypeState(status.state.sample_type as 'au_nanoparticles' | 'fcc_crystal');
        }
        // Get beam settings
        if (status.state.beam) {
          setBeamCurrent(status.state.beam.current_pA || 50);
          setBeamVoltage(status.state.beam.voltage_kV || 200);
        }
        setIs3DMode(status.state.tilt_enabled || true);
      }
      setError(null);
    } catch {
      setIsConnected(false);
      setError('Cannot connect to microscope server');
    }
  };

  const handleAcquire = async () => {
    if (!isConnected) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      const result = await acquireImage('haadf');
      if (result.image?.image_base64) {
        setCurrentImage(result.image.image_base64);
        setImageInfo({
          x_um: result.stage.x_um,
          y_um: result.stage.y_um,
          fov_um: result.settings.field_of_view_um,
          a: tiltA,
          b: tiltB,
          mode: imagingMode,
        });
        onImageAcquired?.(result);
      }
    } catch {
      setError('Failed to acquire image');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAutofocus = async () => {
    if (!isConnected) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      await runAutofocus('haadf', 6.0, 13);
      await handleAcquire();
    } catch {
      setError('Autofocus failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleMove = async (dx: number, dy: number) => {
    if (!isConnected) return;
    
    setIsLoading(true);
    try {
      await setStagePosition({ x: dx * 1e-6, y: dy * 1e-6 }, true);
      await handleAcquire();
    } catch {
      setError('Failed to move stage');
    } finally {
      setIsLoading(false);
    }
  };

  const handleFovChange = async (newFov: number) => {
    if (!isConnected) return;
    
    setFov(newFov);
    setIsLoading(true);
    
    try {
      await setDetectorSettings('haadf', { field_of_view_um: newFov });
      await handleAcquire();
    } catch {
      setError('Failed to change FOV');
    } finally {
      setIsLoading(false);
    }
  };

  const handleTilt = async (da: number, db: number) => {
    if (!isConnected) return;
    
    setIsLoading(true);
    try {
      const newA = tiltA + da;
      const newB = tiltB + db;
      
      const clampedA = Math.max(-60, Math.min(60, newA));
      const clampedB = Math.max(-60, Math.min(60, newB));
      
      await setStagePosition({ a: clampedA, b: clampedB }, false);
      setTiltA(clampedA);
      setTiltB(clampedB);
      await handleAcquire();
    } catch {
      setError('Failed to set tilt');
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetTilt = async () => {
    if (!isConnected) return;
    
    setIsLoading(true);
    try {
      await setStagePosition({ a: 0, b: 0 }, false);
      setTiltA(0);
      setTiltB(0);
      await handleAcquire();
    } catch {
      setError('Failed to reset tilt');
    } finally {
      setIsLoading(false);
    }
  };

  const handleModeChange = async (mode: 'IMG' | 'DIFF') => {
    if (!isConnected || mode === imagingMode) return;
    
    setIsLoading(true);
    try {
      await setMode(mode);
      setImagingMode(mode);
      await handleAcquire();
    } catch {
      setError('Failed to change mode');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSampleChange = async (sample: 'au_nanoparticles' | 'fcc_crystal') => {
    if (!isConnected || sample === sampleType) return;
    
    setIsLoading(true);
    setError(null);
    try {
      await setSampleType(sample);
      setSampleTypeState(sample);
      // Wait a bit for sample to regenerate
      await new Promise(r => setTimeout(r, 500));
      await handleAcquire();
    } catch {
      setError('Failed to change sample');
    } finally {
      setIsLoading(false);
    }
  };

  const handleBeamChange = async (current: number, voltage: number) => {
    if (!isConnected) return;
    
    setIsLoading(true);
    setError(null);
    try {
      await setBeamSettings({ current_pA: current, voltage_kV: voltage });
      setBeamCurrent(current);
      setBeamVoltage(voltage);
      await handleAcquire();
    } catch {
      setError('Failed to update beam settings');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <Scan className="w-5 h-5 text-cyan-400" />
          <span className="font-semibold text-white">STEM Digital Twin</span>
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
        </div>
        <button
          onClick={checkConnection}
          className="p-1.5 hover:bg-slate-700 rounded-md transition-colors"
          title="Refresh connection"
        >
          <RefreshCw className={`w-4 h-4 text-slate-400 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Mode & Sample Toggles */}
      <div className="flex gap-2 p-3 bg-slate-800/50 border-b border-slate-700">
        {/* Imaging Mode Toggle */}
        <div className="flex-1">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Mode</div>
          <div className="flex rounded-lg overflow-hidden border border-slate-600">
            <button
              onClick={() => handleModeChange('IMG')}
              disabled={!isConnected || isLoading}
              className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
                imagingMode === 'IMG'
                  ? 'bg-cyan-600 text-white'
                  : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
              }`}
            >
              <ImageIcon className="w-3 h-3" />
              Imaging
            </button>
            <button
              onClick={() => handleModeChange('DIFF')}
              disabled={!isConnected || isLoading}
              className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
                imagingMode === 'DIFF'
                  ? 'bg-violet-600 text-white'
                  : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
              }`}
            >
              <Sparkles className="w-3 h-3" />
              Diffraction
            </button>
          </div>
        </div>

        {/* Sample Toggle */}
        <div className="flex-1">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Sample</div>
          <div className="flex rounded-lg overflow-hidden border border-slate-600">
            <button
              onClick={() => handleSampleChange('au_nanoparticles')}
              disabled={!isConnected || isLoading}
              className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
                sampleType === 'au_nanoparticles'
                  ? 'bg-amber-600 text-white'
                  : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
              }`}
              title="Gold Nanoparticles"
            >
              <Atom className="w-3 h-3" />
              Au
            </button>
            <button
              onClick={() => handleSampleChange('fcc_crystal')}
              disabled={!isConnected || isLoading}
              className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
                sampleType === 'fcc_crystal'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
              }`}
              title="FCC Single Crystal"
            >
              <Rotate3D className="w-3 h-3" />
              FCC
            </button>
          </div>
        </div>
      </div>

      {/* Image Display */}
      <div className="relative aspect-square bg-black flex items-center justify-center">
        {currentImage ? (
          <img 
            src={currentImage} 
            alt="Microscope view" 
            className="w-full h-full object-contain"
          />
        ) : (
          <div className="text-center text-slate-600">
            <ImageIcon className="w-16 h-16 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No image acquired</p>
            <p className="text-xs mt-1 text-slate-700">Click Acquire to capture</p>
          </div>
        )}
        
        {/* Crosshair overlay */}
        {currentImage && (
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-cyan-500/30" />
            <div className="absolute top-1/2 left-0 right-0 h-px bg-cyan-500/30" />
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
              <Circle className="w-8 h-8 text-cyan-500/50" strokeWidth={1} />
            </div>
          </div>
        )}

        {/* Info overlay */}
        {imageInfo && (
          <div className="absolute bottom-2 left-2 bg-black/80 text-white text-xs px-2 py-1 rounded font-mono">
            ({imageInfo.x_um.toFixed(1)}, {imageInfo.y_um.toFixed(1)}) µm • FOV: {imageInfo.fov_um} µm
            {is3DMode && ` • α=${tiltA.toFixed(1)}° β=${tiltB.toFixed(1)}°`}
          </div>
        )}
        
        {/* Mode badge */}
        <div className={`absolute top-2 right-2 text-white text-xs px-2 py-1 rounded-full flex items-center gap-1 ${
          imagingMode === 'DIFF' ? 'bg-violet-600/90' : 'bg-cyan-600/90'
        }`}>
          {imagingMode === 'DIFF' ? <Sparkles className="w-3 h-3" /> : <ImageIcon className="w-3 h-3" />}
          {imagingMode === 'DIFF' ? 'Diffraction' : 'Imaging'}
        </div>
        
        {/* Sample badge */}
        <div className={`absolute top-2 left-2 text-white text-xs px-2 py-1 rounded-full flex items-center gap-1 ${
          sampleType === 'fcc_crystal' ? 'bg-emerald-600/90' : 'bg-amber-600/90'
        }`}>
          {sampleType === 'fcc_crystal' ? <Rotate3D className="w-3 h-3" /> : <Atom className="w-3 h-3" />}
          {sampleType === 'fcc_crystal' ? 'FCC Crystal' : 'Au Nanoparticles'}
        </div>
        
        {/* Loading overlay */}
        {isLoading && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <div className="flex items-center gap-2 text-cyan-400">
              <Loader2 className="w-6 h-6 animate-spin" />
              <span className="text-sm">Working...</span>
            </div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="p-4 space-y-4 bg-slate-800/50">
        {/* Action buttons */}
        <div className="flex gap-2">
          <button
            onClick={handleAcquire}
            disabled={!isConnected || isLoading}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 bg-cyan-600 hover:bg-cyan-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors text-sm font-medium"
          >
            <Camera className="w-4 h-4" />
            Acquire
          </button>
          <button
            onClick={handleAutofocus}
            disabled={!isConnected || isLoading}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors text-sm font-medium"
          >
            <Focus className="w-4 h-4" />
            Autofocus
          </button>
        </div>

        {/* FOV Control */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <ZoomIn className="w-4 h-4" />
              Field of View
            </span>
            <span className="text-white font-mono text-xs bg-slate-700 px-2 py-0.5 rounded">{fov} µm</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleFovChange(Math.max(5, fov - 5))}
              disabled={!isConnected || isLoading}
              className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
            >
              <ZoomIn className="w-4 h-4 text-white" />
            </button>
            <input
              type="range"
              min="5"
              max="50"
              value={fov}
              onChange={(e) => setFov(Number(e.target.value))}
              onMouseUp={() => handleFovChange(fov)}
              onTouchEnd={() => handleFovChange(fov)}
              className="flex-1 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
            />
            <button
              onClick={() => handleFovChange(Math.min(50, fov + 5))}
              disabled={!isConnected || isLoading}
              className="p-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
            >
              <ZoomOut className="w-4 h-4 text-white" />
            </button>
          </div>
        </div>

        {/* Stage Controls */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-400 flex items-center gap-1">
              <Move className="w-4 h-4" />
              Stage Control
            </span>
            <select
              value={moveStep}
              onChange={(e) => setMoveStep(Number(e.target.value))}
              className="bg-slate-700 text-white text-xs rounded px-2 py-1 border-none focus:ring-1 focus:ring-cyan-500"
            >
              <option value={1}>1 µm</option>
              <option value={5}>5 µm</option>
              <option value={10}>10 µm</option>
              <option value={20}>20 µm</option>
            </select>
          </div>
          
          <div className="flex justify-center">
            <div className="grid grid-cols-3 gap-1">
              <div />
              <button
                onClick={() => handleMove(0, -moveStep)}
                disabled={!isConnected || isLoading}
                className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
              >
                <ArrowUp className="w-4 h-4 text-white" />
              </button>
              <div />
              <button
                onClick={() => handleMove(-moveStep, 0)}
                disabled={!isConnected || isLoading}
                className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
              >
                <ArrowLeft className="w-4 h-4 text-white" />
              </button>
              <button
                onClick={handleAcquire}
                disabled={!isConnected || isLoading}
                className="p-2.5 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 rounded transition-colors"
              >
                <Circle className="w-4 h-4 text-white" />
              </button>
              <button
                onClick={() => handleMove(moveStep, 0)}
                disabled={!isConnected || isLoading}
                className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
              >
                <ArrowRight className="w-4 h-4 text-white" />
              </button>
              <div />
              <button
                onClick={() => handleMove(0, moveStep)}
                disabled={!isConnected || isLoading}
                className="p-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded transition-colors"
              >
                <ArrowDown className="w-4 h-4 text-white" />
              </button>
              <div />
            </div>
          </div>
        </div>

        {/* Tilt Controls */}
        {is3DMode && (
          <div className="space-y-2 pt-2 border-t border-slate-700">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400 flex items-center gap-1">
                <Rotate3D className="w-4 h-4" />
                Tilt Control
              </span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-violet-400 font-mono bg-slate-700 px-2 py-0.5 rounded">
                  α={tiltA.toFixed(1)}° β={tiltB.toFixed(1)}°
                </span>
                <button
                  onClick={handleResetTilt}
                  disabled={!isConnected || isLoading || (tiltA === 0 && tiltB === 0)}
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
                className="bg-slate-700 text-white text-xs rounded px-2 py-1 border-none focus:ring-1 focus:ring-violet-500"
              >
                <option value={1}>1°</option>
                <option value={5}>5°</option>
                <option value={10}>10°</option>
                <option value={15}>15°</option>
              </select>
              
              <div className="flex-1 grid grid-cols-2 gap-2">
                {/* Alpha (X-axis) tilt */}
                <div className="flex items-center gap-1">
                  <span className="text-xs text-slate-500 w-4">α</span>
                  <button
                    onClick={() => handleTilt(-tiltStep, 0)}
                    disabled={!isConnected || isLoading}
                    className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center"
                    title={`Tilt α -${tiltStep}°`}
                  >
                    <RotateCcw className="w-3 h-3 text-white" />
                  </button>
                  <button
                    onClick={() => handleTilt(tiltStep, 0)}
                    disabled={!isConnected || isLoading}
                    className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center"
                    title={`Tilt α +${tiltStep}°`}
                  >
                    <RotateCw className="w-3 h-3 text-white" />
                  </button>
                </div>
                
                {/* Beta (Y-axis) tilt */}
                <div className="flex items-center gap-1">
                  <span className="text-xs text-slate-500 w-4">β</span>
                  <button
                    onClick={() => handleTilt(0, -tiltStep)}
                    disabled={!isConnected || isLoading}
                    className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center"
                    title={`Tilt β -${tiltStep}°`}
                  >
                    <RotateCcw className="w-3 h-3 text-white" />
                  </button>
                  <button
                    onClick={() => handleTilt(0, tiltStep)}
                    disabled={!isConnected || isLoading}
                    className="flex-1 p-1.5 bg-slate-700 hover:bg-violet-600 disabled:opacity-50 rounded transition-colors flex items-center justify-center"
                    title={`Tilt β +${tiltStep}°`}
                  >
                    <RotateCw className="w-3 h-3 text-white" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Beam Controls */}
        <div className="space-y-3 pt-2 border-t border-slate-700">
          <div className="text-sm text-slate-400 flex items-center gap-1">
            <Zap className="w-4 h-4" />
            Beam Settings
          </div>
          
          {/* Voltage Control */}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 flex items-center gap-1">
                <Zap className="w-3 h-3 text-yellow-400" />
                Voltage
              </span>
              <span className="text-yellow-400 font-mono bg-slate-700 px-2 py-0.5 rounded">{beamVoltage} kV</span>
            </div>
            <input
              type="range"
              min="60"
              max="300"
              step="10"
              value={beamVoltage}
              onChange={(e) => setBeamVoltage(Number(e.target.value))}
              onMouseUp={() => handleBeamChange(beamCurrent, beamVoltage)}
              onTouchEnd={() => handleBeamChange(beamCurrent, beamVoltage)}
              disabled={!isConnected || isLoading}
              className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-yellow-500 disabled:opacity-50"
            />
            <div className="flex justify-between text-[10px] text-slate-600">
              <span>60 kV</span>
              <span>300 kV</span>
            </div>
          </div>

          {/* Current Control */}
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
              min="5"
              max="200"
              step="5"
              value={beamCurrent}
              onChange={(e) => setBeamCurrent(Number(e.target.value))}
              onMouseUp={() => handleBeamChange(beamCurrent, beamVoltage)}
              onTouchEnd={() => handleBeamChange(beamCurrent, beamVoltage)}
              disabled={!isConnected || isLoading}
              className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-orange-500 disabled:opacity-50"
            />
            <div className="flex justify-between text-[10px] text-slate-600">
              <span>5 pA</span>
              <span>200 pA</span>
            </div>
          </div>
        </div>

        {/* Error display */}
        {error && (
          <div className="text-red-400 text-xs text-center py-2 bg-red-900/20 rounded-lg border border-red-900/50">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
