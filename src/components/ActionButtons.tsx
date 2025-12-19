import { Download, Play, Sparkles } from 'lucide-react';

interface ActionButtonsProps {
  isConnected: boolean;
  planGenerated: boolean;
  onGeneratePlan: () => void;
  onExportJSON: () => void;
  onStartRun: () => void;
  isRunning: boolean;
}

export function ActionButtons({
  isConnected,
  planGenerated,
  onGeneratePlan,
  onExportJSON,
  onStartRun,
  isRunning,
}: ActionButtonsProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Actions</h2>

      <div className="space-y-3">
        <button
          onClick={onGeneratePlan}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
        >
          <Sparkles className="w-5 h-5" />
          Generate Plan
        </button>

        <button
          onClick={onExportJSON}
          disabled={!planGenerated}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium"
        >
          <Download className="w-5 h-5" />
          Export JSON
        </button>

        <button
          onClick={onStartRun}
          disabled={!isConnected || !planGenerated || isRunning}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium"
        >
          <Play className="w-5 h-5" />
          {isRunning ? 'Running...' : 'Start Run'}
        </button>

        {!isConnected && planGenerated && (
          <p className="text-xs text-amber-600 text-center">
            Connect to microscope to start run
          </p>
        )}
      </div>
    </div>
  );
}
