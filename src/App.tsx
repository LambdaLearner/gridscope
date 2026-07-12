import { useCallback, useState } from 'react';
import { Microscope, FlaskConical, Bot, PanelRightClose, PanelRightOpen, ScrollText, ChevronDown, ChevronRight } from 'lucide-react';
import { AIAssistant } from './components/AIAssistant';
import { SampleSettingsPanel } from './components/SampleSettingsPanel';
import { MicroscopeControlsPanel } from './components/MicroscopeControlsPanel';
import { ExecutionPanel } from './components/ExecutionPanel';
import { MicroscopeLogsPanel } from './components/MicroscopeLogsPanel';
import { SessionSeedsStrip } from './components/SessionSeedsStrip';
import { useMicroscopeSession } from './hooks/useMicroscopeSession';
import { useCodeExecution } from './hooks/useCodeExecution';

type Tab = 'sample' | 'microscope';

function App() {
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('sample');
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [logOpen, setLogOpen] = useState(false);

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

  const tabClass = (tab: Tab) =>
    `flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-t-lg transition-colors border-b-2 ${
      activeTab === tab
        ? 'text-white border-cyan-400 bg-slate-800/60'
        : 'text-slate-500 border-transparent hover:text-slate-300'
    }`;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="bg-slate-900/80 backdrop-blur-sm border-b border-slate-800 sticky top-0 z-40">
        <div className="max-w-[2000px] mx-auto px-6 py-3">
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

              <button
                onClick={() => setDrawerOpen((v) => !v)}
                title={drawerOpen ? 'Hide AI assistant' : 'Show AI assistant'}
                className="p-1.5 hover:bg-slate-800 rounded-md text-slate-400 transition-colors"
              >
                {drawerOpen ? <PanelRightClose className="w-5 h-5" /> : <PanelRightOpen className="w-5 h-5" />}
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Session seeds (reproducibility) — spans both tabs */}
      <SessionSeedsStrip session={session} disabled={runActive || isExecuting} onApplied={refresh} />

      {/* Tabs */}
      <div className="max-w-[2000px] mx-auto px-6 pt-3">
        <div className="flex gap-1 border-b border-slate-800">
          <button className={tabClass('sample')} onClick={() => setActiveTab('sample')}>
            <FlaskConical className="w-4 h-4" />
            Sample &amp; Environment
          </button>
          <button className={tabClass('microscope')} onClick={() => setActiveTab('microscope')}>
            <Microscope className="w-4 h-4" />
            Microscope
          </button>
        </div>
      </div>

      {/* Main content: active tab + AI drawer */}
      <main className="max-w-[2000px] mx-auto px-6 py-4">
        <div className={`grid grid-cols-1 gap-6 ${drawerOpen ? 'xl:grid-cols-3' : ''}`}>
          <div className={drawerOpen ? 'xl:col-span-2' : ''}>
            {activeTab === 'sample' ? (
              <SampleSettingsPanel
                session={session}
                runActive={runActive || isExecuting}
                onRegistered={refresh}
              />
            ) : (
              <div className="max-w-2xl mx-auto">
                <MicroscopeControlsPanel
                  session={session}
                  sampleRegistered={sampleRegistered}
                  runActive={runActive || isExecuting}
                  onAcquired={refresh}
                />
              </div>
            )}

            {/* Command log strip (spec §3.2) — spans both tabs */}
            <div className="mt-4">
              <button
                onClick={() => setLogOpen((v) => !v)}
                className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 mb-2"
              >
                {logOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                <ScrollText className="w-3.5 h-3.5" />
                Command log ({session?.log?.length ?? 0}) — the exact RPCs your clicks produced
              </button>
              {logOpen && <MicroscopeLogsPanel log={session?.log ?? []} />}
            </div>
          </div>

          {/* AI assistant + execution drawer */}
          {drawerOpen && (
            <div className="xl:col-span-1 space-y-6">
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <Bot className="w-4 h-4 text-violet-400" />
                AI Assistant &amp; Script Execution
              </div>
              <AIAssistant
                experimentConfig={null}
                onCodeGenerated={handleCodeGenerated}
                onRunCode={handleRun}
              />
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
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
