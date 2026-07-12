import { useCallback, useState } from 'react';
import { Microscope } from 'lucide-react';
import { AIAssistant } from './components/AIAssistant';
import { SampleSettingsPanel } from './components/SampleSettingsPanel';
import { MicroscopeControlsPanel } from './components/MicroscopeControlsPanel';
import { ExecutionPanel } from './components/ExecutionPanel';
import { MicroscopeLogsPanel } from './components/MicroscopeLogsPanel';
import { useMicroscopeSession } from './hooks/useMicroscopeSession';
import { useCodeExecution } from './hooks/useCodeExecution';

function App() {
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);

  // Single session poller feeding every panel (state, sample, run, log).
  const { session, connected, sampleRegistered, runActive, refresh } =
    useMicroscopeSession(2000);

  const {
    executionLogs,
    acquiredImages,
    isExecuting,
    handleRunCode,
    handleStopExecution,
  } = useCodeExecution();

  const handleCodeGenerated = useCallback((code: string) => {
    setGeneratedCode(code);
  }, []);

  const handleRun = useCallback(
    async (code: string) => {
      setGeneratedCode(code);
      await handleRunCode(code);
      refresh();
    },
    [handleRunCode, refresh],
  );

  const handleStartExecution = useCallback(() => {
    if (generatedCode) handleRun(generatedCode);
  }, [generatedCode, handleRun]);

  const stage = session?.state?.stage;
  const fovUm = session?.state?.detectors?.haadf?.field_of_view_um;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="bg-slate-900/80 backdrop-blur-sm border-b border-slate-800 sticky top-0 z-40">
        <div className="max-w-[2000px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-gradient-to-br from-violet-600 to-cyan-600 rounded-xl shadow-lg shadow-violet-500/20">
                <Microscope className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-violet-400 to-cyan-400 bg-clip-text text-transparent">
                  GridScope
                </h1>
                <p className="text-sm text-slate-500">STEM Digital Twin AI Assistant</p>
              </div>
            </div>

            {/* Status indicators */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
                <span className="text-sm text-slate-400">
                  {connected ? 'Connected' : 'Disconnected'}
                </span>
              </div>

              {connected && (
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${sampleRegistered ? 'bg-amber-400' : 'bg-slate-600'}`} />
                  <span className="text-sm text-slate-400">
                    {sampleRegistered ? session?.sample?.name : 'No sample'}
                  </span>
                </div>
              )}

              {stage && (
                <div className="hidden md:flex items-center gap-4 text-xs text-slate-500 font-mono">
                  <span>X: {(stage.x * 1e6).toFixed(1)} µm</span>
                  <span>Y: {(stage.y * 1e6).toFixed(1)} µm</span>
                  {fovUm !== undefined && <span>FOV: {fovUm.toFixed(1)} µm</span>}
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-[2000px] mx-auto px-6 py-6">
        <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
          {/* Column 1: Sample Settings (simulation-only window) */}
          <div className="xl:col-span-1 space-y-6">
            <SampleSettingsPanel
              session={session}
              runActive={runActive || isExecuting}
              onRegistered={refresh}
            />
            <MicroscopeLogsPanel log={session?.log ?? []} />
          </div>

          {/* Column 2: Microscope Controls (portable control surface) */}
          <div className="xl:col-span-1">
            <MicroscopeControlsPanel
              session={session}
              sampleRegistered={sampleRegistered}
              runActive={runActive || isExecuting}
              onAcquired={refresh}
            />
          </div>

          {/* Column 3: AI Assistant */}
          <div className="xl:col-span-1">
            <AIAssistant
              experimentConfig={null}
              onCodeGenerated={handleCodeGenerated}
              onRunCode={handleRun}
            />
          </div>

          {/* Column 4: Execution Output */}
          <div className="xl:col-span-1">
            <ExecutionPanel
              code={generatedCode}
              isRunning={isExecuting}
              onStart={handleStartExecution}
              onStop={handleStopExecution}
              logs={executionLogs}
              acquiredImages={acquiredImages}
              currentSampleType={session?.sample?.name ?? ''}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
