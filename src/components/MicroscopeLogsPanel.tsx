import { useEffect, useRef, useState } from 'react';
import {
  Terminal,
  Camera,
  Move,
  Focus,
  Settings,
  Eye,
  Clock,
  ChevronDown,
  ChevronUp,
  FlaskConical,
} from 'lucide-react';
import type { CommandLogEntry } from '../api/digitalTwin';

interface MicroscopeLogsPanelProps {
  /** Command log entries from the shared session poller. */
  log: CommandLogEntry[];
}

function getMethodIcon(method: string) {
  if (method.includes('acquire')) return <Camera className="w-3 h-3 text-cyan-400" />;
  if (method.includes('stage')) return <Move className="w-3 h-3 text-emerald-400" />;
  if (method.includes('focus')) return <Focus className="w-3 h-3 text-violet-400" />;
  if (method.includes('sample') || method.includes('environment') || method.includes('specimen'))
    return <FlaskConical className="w-3 h-3 text-amber-400" />;
  if (method.includes('settings') || method.includes('magnification'))
    return <Settings className="w-3 h-3 text-orange-400" />;
  if (method.startsWith('get')) return <Eye className="w-3 h-3 text-slate-500" />;
  return <Terminal className="w-3 h-3 text-slate-400" />;
}

export function MicroscopeLogsPanel({ log }: MicroscopeLogsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const prevLength = useRef(0);

  useEffect(() => {
    if (isExpanded && log.length > prevLength.current) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevLength.current = log.length;
  }, [log, isExpanded]);

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-emerald-400" />
          <span className="font-semibold text-white text-sm">Microscope Command Log</span>
          <span className="text-xs text-slate-500">({log.length})</span>
        </div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="p-1.5 hover:bg-slate-700 rounded-md transition-colors"
        >
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          )}
        </button>
      </div>

      {isExpanded && (
        <div className="max-h-64 overflow-y-auto p-3 space-y-1">
          {log.length === 0 ? (
            <div className="text-center text-slate-600 py-6">
              <Clock className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p className="text-xs">No commands logged yet</p>
            </div>
          ) : (
            log.map((entry, idx) => (
              <div key={`${entry.t}-${idx}`} className="flex items-start gap-2 text-xs py-1 border-b border-slate-800 last:border-b-0">
                <span className="mt-0.5 flex-shrink-0">{getMethodIcon(entry.method)}</span>
                <div className="flex-1 min-w-0">
                  <span className="text-slate-300 font-mono">{entry.method}</span>
                  {entry.result_preview && (
                    <span className="text-slate-600 ml-2 truncate">{entry.result_preview.slice(0, 80)}</span>
                  )}
                </div>
                <span className="text-[10px] text-slate-600 flex-shrink-0 font-mono">
                  {new Date(entry.t * 1000).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      )}
    </div>
  );
}
