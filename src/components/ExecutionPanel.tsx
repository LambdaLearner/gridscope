import { useState, useEffect, useRef } from 'react';
import { 
  Play, 
  Square, 
  Terminal, 
  CheckCircle2, 
  XCircle, 
  Clock, 
  Image as ImageIcon,
  Loader2,
  ChevronDown,
  ChevronUp
} from 'lucide-react';

interface ExecutionLog {
  id: string;
  type: 'info' | 'success' | 'error' | 'image' | 'stage' | 'command';
  message: string;
  timestamp: Date;
  data?: {
    image_base64?: string;
    stage?: { x_um: number; y_um: number; z_um: number; a?: number; b?: number };
    command?: string;
    sampleType?: string;
    mode?: string;
  };
}

interface AcquiredImageData {
  image_base64: string;
  x_um: number;
  y_um: number;
  z_um?: number;
  a?: number;  // alpha tilt angle
  b?: number;  // beta tilt angle
  sampleType?: string;
  mode?: string;
}

interface ExecutionPanelProps {
  code: string | null;
  isRunning: boolean;
  onStart: () => void;
  onStop: () => void;
  logs: ExecutionLog[];
  acquiredImages: AcquiredImageData[];
  currentSampleType?: string;
  currentMode?: string;
}

export function ExecutionPanel({ 
  code, 
  isRunning, 
  onStart, 
  onStop, 
  logs,
  acquiredImages,
  currentSampleType = 'au_nanoparticles',
  currentMode = 'IMG'
}: ExecutionPanelProps) {
  const [showCode, setShowCode] = useState(false);
  const [selectedImage, setSelectedImage] = useState<number | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const [userHasScrolled, setUserHasScrolled] = useState(false);

  // Auto-scroll only during active execution and if user hasn't manually scrolled up
  useEffect(() => {
    if (isRunning && !userHasScrolled) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isRunning, userHasScrolled]);

  // Reset scroll tracking when execution starts
  useEffect(() => {
    if (isRunning) {
      setUserHasScrolled(false);
    }
  }, [isRunning]);

  // Detect user scroll - don't auto-scroll if user scrolled up
  const handleScroll = () => {
    if (!logsContainerRef.current || !isRunning) return;
    const { scrollTop, scrollHeight, clientHeight } = logsContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setUserHasScrolled(!isAtBottom);
  };

  // Helper to get sample label
  const getSampleLabel = (sampleType?: string) => {
    if (sampleType === 'fcc_crystal') return 'FCC Crystal';
    return 'Au Nanoparticles';
  };

  const getLogIcon = (type: ExecutionLog['type']) => {
    switch (type) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-400" />;
      case 'image':
        return <ImageIcon className="w-4 h-4 text-cyan-400" />;
      case 'command':
        return <Terminal className="w-4 h-4 text-violet-400" />;
      default:
        return <Clock className="w-4 h-4 text-slate-400" />;
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-emerald-400" />
          <h3 className="font-semibold text-white">Execution Output</h3>
          {isRunning && (
            <span className="flex items-center gap-1 text-xs text-amber-400 bg-amber-900/30 px-2 py-0.5 rounded-full">
              <Loader2 className="w-3 h-3 animate-spin" />
              Running
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {code && (
            <button
              onClick={() => setShowCode(!showCode)}
              className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded transition-colors"
            >
              {showCode ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              Code
            </button>
          )}
          {!isRunning && code && (
            <button
              onClick={onStart}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors"
            >
              <Play className="w-3 h-3" />
              Run
            </button>
          )}
          {isRunning && (
            <button
              onClick={onStop}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
            >
              <Square className="w-3 h-3" />
              Stop
            </button>
          )}
        </div>
      </div>

      {/* Code Preview (collapsible) */}
      {showCode && code && (
        <div className="bg-slate-950 border-b border-slate-700 max-h-48 overflow-auto">
          <pre className="p-4 text-xs text-slate-300 font-mono whitespace-pre-wrap">
            {code}
          </pre>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Logs */}
        <div 
          ref={logsContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto p-4 space-y-2"
        >
          {logs.length === 0 ? (
            <div className="h-full flex items-center justify-center text-slate-500">
              <div className="text-center">
                <Terminal className="w-12 h-12 mx-auto mb-3 opacity-30" />
                <p className="text-sm">No execution logs yet</p>
                <p className="text-xs mt-1">Generate and run a script to see output here</p>
              </div>
            </div>
          ) : (
            logs.map((log) => (
              <div
                key={log.id}
                className="animate-in slide-in-from-left-2 duration-200"
              >
                <div className="flex items-start gap-2 text-sm">
                  <span className="mt-0.5 flex-shrink-0">
                    {getLogIcon(log.type)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <span className={`${
                      log.type === 'error' ? 'text-red-300' :
                      log.type === 'success' ? 'text-emerald-300' :
                      log.type === 'command' ? 'text-violet-300' :
                      log.type === 'image' ? 'text-cyan-300' :
                      'text-slate-300'
                    }`}>
                      {log.message}
                    </span>
                    {log.data?.stage && !log.data?.image_base64 && (
                      <div className="mt-1 text-xs text-slate-500 font-mono">
                        Stage: X={log.data.stage.x_um.toFixed(2)} µm, Y={log.data.stage.y_um.toFixed(2)} µm
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] text-slate-600 flex-shrink-0">
                    {log.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                </div>
                
                {/* Inline image preview for image logs */}
                {log.type === 'image' && log.data?.image_base64 && (
                  <div className="mt-2 ml-6 flex items-start gap-3 bg-slate-800/50 rounded-lg p-2 border border-slate-700">
                    <img 
                      src={log.data.image_base64} 
                      alt="Acquired" 
                      className="w-24 h-24 object-cover rounded border border-slate-600"
                    />
                    <div className="text-xs text-slate-400">
                      <div className="font-mono">
                        Position: ({log.data.stage?.x_um?.toFixed(2) || '0.00'}, {log.data.stage?.y_um?.toFixed(2) || '0.00'}, {log.data.stage?.z_um?.toFixed(2) || '0.00'}) µm
                      </div>
                      {(log.data.stage?.a !== undefined || log.data.stage?.b !== undefined) && (
                        <div className="font-mono text-violet-400">
                          α={log.data.stage?.a?.toFixed(1) || 0}° β={log.data.stage?.b?.toFixed(1) || 0}°
                        </div>
                      )}
                      <div className="mt-1 text-slate-500">
                        256×256 px • {getSampleLabel(log.data.sampleType || currentSampleType)}
                        {log.data.mode === 'DIFF' && ' • Diffraction'}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>

        {/* Acquired Images Sidebar */}
        {acquiredImages.length > 0 && (
          <div className="w-48 border-l border-slate-700 bg-slate-800/50 p-3 overflow-y-auto">
            <h4 className="text-xs font-medium text-slate-400 mb-2 flex items-center gap-1">
              <ImageIcon className="w-3 h-3" />
              Acquired ({acquiredImages.length})
            </h4>
            <div className="space-y-2">
              {acquiredImages.map((img, idx) => (
                <button
                  key={idx}
                  onClick={() => setSelectedImage(selectedImage === idx ? null : idx)}
                  className={`w-full aspect-square rounded-lg overflow-hidden border-2 transition-all ${
                    selectedImage === idx 
                      ? 'border-cyan-400 shadow-lg shadow-cyan-400/20' 
                      : 'border-slate-600 hover:border-slate-500'
                  }`}
                >
                  <img 
                    src={img.image_base64} 
                    alt={`Tile ${idx}`}
                    className="w-full h-full object-cover"
                  />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Selected Image Preview */}
      {selectedImage !== null && acquiredImages[selectedImage] && (
        <div className="border-t border-slate-700 bg-slate-800 p-4">
          <div className="flex items-center justify-between mb-2">
            <div>
              <span className="text-sm text-white font-medium">
                Image {selectedImage + 1}
              </span>
              <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
                acquiredImages[selectedImage].sampleType === 'fcc_crystal' 
                  ? 'bg-emerald-600/20 text-emerald-400' 
                  : 'bg-amber-600/20 text-amber-400'
              }`}>
                {getSampleLabel(acquiredImages[selectedImage].sampleType || currentSampleType)}
              </span>
              {acquiredImages[selectedImage].mode === 'DIFF' && (
                <span className="ml-1 text-xs px-1.5 py-0.5 rounded bg-violet-600/20 text-violet-400">
                  Diffraction
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400 font-mono text-right">
              <div>({acquiredImages[selectedImage].x_um.toFixed(2)}, {acquiredImages[selectedImage].y_um.toFixed(2)}, {acquiredImages[selectedImage].z_um?.toFixed(2) || '0.00'}) µm</div>
              {(acquiredImages[selectedImage].a !== undefined || acquiredImages[selectedImage].b !== undefined) && (
                <div className="text-violet-400">
                  α={acquiredImages[selectedImage].a?.toFixed(1) || 0}° β={acquiredImages[selectedImage].b?.toFixed(1) || 0}°
                </div>
              )}
            </div>
          </div>
          <img 
            src={acquiredImages[selectedImage].image_base64}
            alt="Selected"
            className="w-full max-h-64 object-contain rounded-lg bg-black"
          />
        </div>
      )}
    </div>
  );
}

