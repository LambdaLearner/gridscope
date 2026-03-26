import { useState, useCallback } from 'react';
import { Microscope } from 'lucide-react';
import { AIAssistant } from './components/AIAssistant';
import { MicroscopeViewer } from './components/MicroscopeViewer';
import { ExecutionPanel } from './components/ExecutionPanel';
import { MicroscopeLogsPanel } from './components/MicroscopeLogsPanel';
import { type MicroscopeState, type AcquireResult } from './api/digitalTwin';
import { useCodeExecution } from './hooks/useCodeExecution';
import type { ExecutionPlan } from './types/execution';

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [microscopeState, setMicroscopeState] = useState<MicroscopeState | null>(null);
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [currentSampleType, setCurrentSampleType] = useState<string>('au_nanoparticles');
  const [currentMode, setCurrentMode] = useState<string>('IMG');
  const [currentPlan, setCurrentPlan] = useState<ExecutionPlan | undefined>(undefined);

  const {
    executionLogs,
    acquiredImages,
    isExecuting,
    handleRunCode,
  } = useCodeExecution(currentSampleType, currentMode, setCurrentSampleType, setCurrentMode);

  // Handle microscope state updates from viewer
  const handleMicroscopeStateChange = useCallback((state: MicroscopeState) => {
    setMicroscopeState(state);
    setIsConnected(true);
    if (state.sample_type) {
      setCurrentSampleType(state.sample_type);
    }
    if (state.mode) {
      setCurrentMode(state.mode);
    }
  }, []);

  // Handle image acquisition from viewer (manual acquire button)
  const handleImageAcquired = useCallback((_result: AcquireResult) => {
    // Images from the viewer are handled independently by MicroscopeViewer.
    // The hook manages images from code execution.
  }, []);

  // Handle code generation
  const handleCodeGenerated = useCallback((code: string) => {
    setGeneratedCode(code);
  }, []);

  // Handle run — passes execution plan if available
  const handleRunCodeWithPlan = useCallback(async (code: string, executionPlan?: ExecutionPlan) => {
    // Store the plan for potential re-runs
    if (executionPlan) setCurrentPlan(executionPlan);
    await handleRunCode(code, executionPlan);
  }, [handleRunCode]);

  // Start execution (from ExecutionPanel button)
  const handleStartExecution = useCallback(() => {
    if (generatedCode) {
      handleRunCode(generatedCode, currentPlan);
    }
  }, [generatedCode, currentPlan, handleRunCode]);

  // Stop execution
  const handleStopExecution = useCallback(() => {
    // The hook doesn't support abort yet, but we can show intent
  }, []);

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
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
                <span className="text-sm text-slate-400">
                  {isConnected ? 'Connected' : 'Disconnected'}
                </span>
              </div>

              {microscopeState && (
                <div className="hidden md:flex items-center gap-4 text-xs text-slate-500 font-mono">
                  <span>X: {(microscopeState.stage.x * 1e6).toFixed(1)} µm</span>
                  <span>Y: {(microscopeState.stage.y * 1e6).toFixed(1)} µm</span>
                  <span>FOV: {microscopeState.detectors?.haadf?.field_of_view_um || 20} µm</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-[2000px] mx-auto px-6 py-6">
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">

          {/* Left Column: Microscope Viewer */}
          <div className="xl:col-span-1 space-y-6">
            <MicroscopeViewer
              onStateChange={handleMicroscopeStateChange}
              onImageAcquired={handleImageAcquired}
            />

            {/* Microscope Command Log */}
            <MicroscopeLogsPanel
              autoRefresh={true}
              refreshInterval={2000}
            />
          </div>

          {/* Middle Column: AI Assistant */}
          <div className="xl:col-span-1">
            <AIAssistant
              experimentConfig={null}
              onCodeGenerated={handleCodeGenerated}
              onRunCode={handleRunCodeWithPlan}
            />
          </div>

          {/* Right Column: Execution Output */}
          <div className="xl:col-span-1">
            <ExecutionPanel
              code={generatedCode}
              isRunning={isExecuting}
              onStart={handleStartExecution}
              onStop={handleStopExecution}
              logs={executionLogs}
              acquiredImages={acquiredImages}
              currentSampleType={currentSampleType}
              currentMode={currentMode}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
