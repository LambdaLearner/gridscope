import { Grid3x3, Crosshair } from 'lucide-react';

interface GridSettingsProps {
  overlapPercent: number;
  stepSize: number;
  startX: number;
  startY: number;
  onOverlapChange: (value: number) => void;
  onStartXChange: (value: number) => void;
  onStartYChange: (value: number) => void;
  onUseCurrentPosition: () => void;
  isLoadingPosition: boolean;
}

export function GridSettings({
  overlapPercent,
  stepSize,
  startX,
  startY,
  onOverlapChange,
  onStartXChange,
  onStartYChange,
  onUseCurrentPosition,
  isLoadingPosition,
}: GridSettingsProps) {
  const handleOverlapChange = (value: number) => {
    const clamped = Math.max(0, Math.min(90, value));
    onOverlapChange(clamped);
  };

  return (
    <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Grid Plan</h2>

      <div className="space-y-4">
        <div className="flex items-center gap-2 text-sm text-gray-600 bg-gray-50 px-3 py-2 rounded-lg">
          <Grid3x3 className="w-4 h-4" />
          <span>Grid Size: <span className="font-semibold text-gray-900">5 × 5</span> (25 tiles)</span>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Overlap Percent
          </label>
          <input
            type="number"
            value={overlapPercent}
            onChange={(e) => handleOverlapChange(parseFloat(e.target.value) || 0)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            min="0"
            max="90"
            step="1"
          />
          <p className="mt-1 text-xs text-gray-500">Range: 0-90%</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Step Size (calculated)
          </label>
          <div className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-700 font-mono">
            {stepSize.toFixed(2)} µm
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Start Position
          </label>
          <div className="grid grid-cols-2 gap-2 mb-2">
            <div>
              <label className="block text-xs text-gray-500 mb-1">X (µm)</label>
              <input
                type="number"
                value={startX}
                onChange={(e) => onStartXChange(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                step="0.1"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Y (µm)</label>
              <input
                type="number"
                value={startY}
                onChange={(e) => onStartYChange(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                step="0.1"
              />
            </div>
          </div>
          <button
            onClick={onUseCurrentPosition}
            disabled={isLoadingPosition}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:bg-gray-100 disabled:cursor-not-allowed transition-colors text-sm"
          >
            <Crosshair className="w-4 h-4" />
            {isLoadingPosition ? 'Loading...' : 'Use Current Stage Position'}
          </button>
        </div>
      </div>
    </div>
  );
}
