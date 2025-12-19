interface AutomationSettingsProps {
  autofocus: boolean;
  aberrationCorrection: boolean;
  dwellTime: number;
  onAutofocusChange: (value: boolean) => void;
  onAberrationCorrectionChange: (value: boolean) => void;
  onDwellTimeChange: (value: number) => void;
}

export function AutomationSettings({
  autofocus,
  aberrationCorrection,
  dwellTime,
  onAutofocusChange,
  onAberrationCorrectionChange,
  onDwellTimeChange,
}: AutomationSettingsProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Automation</h2>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="text-sm font-medium text-gray-700">
              Run autofocus at every tile
            </label>
            <p className="text-xs text-gray-500 mt-0.5">
              Ensures sharp focus for each position
            </p>
          </div>
          <button
            onClick={() => onAutofocusChange(!autofocus)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              autofocus ? 'bg-blue-600' : 'bg-gray-300'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                autofocus ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <label className="text-sm font-medium text-gray-700">
              Run auto aberration correction at every tile
            </label>
            <p className="text-xs text-gray-500 mt-0.5">
              Improves image quality (adds ~5s per tile)
            </p>
          </div>
          <button
            onClick={() => onAberrationCorrectionChange(!aberrationCorrection)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              aberrationCorrection ? 'bg-blue-600' : 'bg-gray-300'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                aberrationCorrection ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Dwell Time per Tile
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={dwellTime}
              onChange={(e) => onDwellTimeChange(parseFloat(e.target.value) || 0)}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              min="0"
              step="0.1"
            />
            <span className="text-sm font-medium text-gray-600">seconds</span>
          </div>
        </div>
      </div>
    </div>
  );
}
