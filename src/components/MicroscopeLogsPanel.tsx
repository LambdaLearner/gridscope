import { useState, useEffect, useRef } from 'react';
import { 
  Terminal, 
  RefreshCw, 
  Trash2, 
  Camera, 
  Move, 
  Focus, 
  Settings, 
  Eye,
  Clock,
  ChevronDown,
  ChevronUp
} from 'lucide-react';

interface CommandLog {
  t: number;
  method: string;
  params: Record<string, unknown>;
  result_preview: string;
}

interface MicroscopeLogsPanelProps {
  autoRefresh?: boolean;
  refreshInterval?: number;
}

export function MicroscopeLogsPanel({ 
  autoRefresh = true, 
  refreshInterval = 2000 
}: MicroscopeLogsPanelProps) {
  const [logs, setLogs] = useState<CommandLog[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const prevLogsLength = useRef(0);

  const fetchLogs = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/microscope/log?last_n=100');
      if (response.ok) {
        const data = await response.json();
        setLogs(data.log || []);
        setError(null);
      } else {
        setError('Failed to fetch logs');
      }
    } catch {
      setError('Cannot connect to microscope');
    }
  };

  const clearLogs = async () => {
    try {
      await fetch('http://localhost:8000/api/microscope/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: 'clear_command_log', params: {} }),
      });
      setLogs([]);
    } catch {
      // Ignore
    }
  };

  const handleRefresh = async () => {
    setIsLoading(true);
    await fetchLogs();
    setIsLoading(false);
  };

  // Auto-refresh
  useEffect(() => {
    fetchLogs();
    
    if (autoRefresh) {
      const interval = setInterval(fetchLogs, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [autoRefresh, refreshInterval]);

  // Scroll to bottom when new logs arrive
  useEffect(() => {
    if (logs.length > prevLogsLength.current) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevLogsLength.current = logs.length;
  }, [logs]);

  const getMethodIcon = (method: string) => {
    switch (method) {
      case 'acquire_image':
        return <Camera className="w-3.5 h-3.5 text-cyan-400" />;
      case 'set_stage':
        return <Move className="w-3.5 h-3.5 text-amber-400" />;
      case 'autofocus':
        return <Focus className="w-3.5 h-3.5 text-violet-400" />;
      case 'device_settings':
        return <Settings className="w-3.5 h-3.5 text-emerald-400" />;
      case 'get_stage':
      case 'get_microscope_state':
      case 'get_detectors':
      case 'get_detector_settings':
        return <Eye className="w-3.5 h-3.5 text-slate-400" />;
      default:
        return <Terminal className="w-3.5 h-3.5 text-slate-400" />;
    }
  };

  const getMethodColor = (method: string) => {
    switch (method) {
      case 'acquire_image':
        return 'border-cyan-500/30 bg-cyan-500/5';
      case 'set_stage':
        return 'border-amber-500/30 bg-amber-500/5';
      case 'autofocus':
        return 'border-violet-500/30 bg-violet-500/5';
      case 'device_settings':
        return 'border-emerald-500/30 bg-emerald-500/5';
      default:
        return 'border-slate-600 bg-slate-800/30';
    }
  };

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit',
      hour12: false 
    });
  };

  const formatParams = (params: Record<string, unknown>) => {
    if (!params || Object.keys(params).length === 0) return null;
    
    const entries = Object.entries(params);
    if (entries.length === 0) return null;
    
    return entries.map(([key, value]) => {
      let displayValue: string;
      
      if (typeof value === 'number') {
        // Format numbers nicely
        if (Math.abs(value) < 0.001 || Math.abs(value) > 1000000) {
          displayValue = value.toExponential(2);
        } else {
          displayValue = value.toFixed(4).replace(/\.?0+$/, '');
        }
      } else if (typeof value === 'object') {
        displayValue = JSON.stringify(value);
      } else {
        displayValue = String(value);
      }
      
      return `${key}=${displayValue}`;
    }).join(', ');
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
      {/* Header */}
      <div 
        className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700 cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-emerald-400" />
          <h3 className="font-semibold text-white">Microscope Command Log</h3>
          <span className="text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded-full">
            {logs.length} commands
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); handleRefresh(); }}
            className="p-1.5 hover:bg-slate-700 rounded transition-colors"
            title="Refresh logs"
          >
            <RefreshCw className={`w-4 h-4 text-slate-400 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); clearLogs(); }}
            className="p-1.5 hover:bg-slate-700 rounded transition-colors"
            title="Clear logs"
          >
            <Trash2 className="w-4 h-4 text-slate-400" />
          </button>
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          )}
        </div>
      </div>

      {/* Logs */}
      {isExpanded && (
        <div className="max-h-80 overflow-y-auto">
          {error ? (
            <div className="p-4 text-center text-slate-500">
              <Terminal className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p className="text-sm">{error}</p>
              <p className="text-xs mt-1">Start the Digital Twin server to see logs</p>
            </div>
          ) : logs.length === 0 ? (
            <div className="p-4 text-center text-slate-500">
              <Terminal className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p className="text-sm">No commands executed yet</p>
              <p className="text-xs mt-1">Interact with the microscope to see logs</p>
            </div>
          ) : (
            <div className="p-3 space-y-2">
              {logs.map((log, idx) => (
                <div
                  key={`${log.t}-${idx}`}
                  className={`p-2.5 rounded-lg border ${getMethodColor(log.method)} animate-in fade-in duration-200`}
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 flex-shrink-0">
                      {getMethodIcon(log.method)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <code className="text-sm font-medium text-white">
                          {log.method}
                        </code>
                        <span className="text-[10px] text-slate-500 flex items-center gap-1 flex-shrink-0">
                          <Clock className="w-3 h-3" />
                          {formatTime(log.t)}
                        </span>
                      </div>
                      
                      {formatParams(log.params) && (
                        <div className="mt-1 text-xs text-slate-400 font-mono truncate">
                          {formatParams(log.params)}
                        </div>
                      )}
                      
                      {log.result_preview && log.result_preview !== 'None' && log.result_preview !== '1' && (
                        <div className="mt-1 text-xs text-slate-500 truncate">
                          → {log.result_preview.substring(0, 80)}
                          {log.result_preview.length > 80 ? '...' : ''}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

