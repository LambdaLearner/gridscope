import { Unit, CurrentUnit } from '../types/config';

interface ImagingSettingsProps {
  fov: number;
  fovUnit: Unit;
  voltage: number;
  currentValue: number;
  currentUnit: CurrentUnit;
  onFovChange: (value: number) => void;
  onFovUnitChange: (unit: Unit) => void;
  onVoltageChange: (value: number) => void;
  onCurrentValueChange: (value: number) => void;
  onCurrentUnitChange: (unit: CurrentUnit) => void;
}

export function ImagingSettings({
  fov,
  fovUnit,
  voltage,
  currentValue,
  currentUnit,
  onFovChange,
  onFovUnitChange,
  onVoltageChange,
  onCurrentValueChange,
  onCurrentUnitChange,
}: ImagingSettingsProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Imaging Settings</h2>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Field of View (FOV)
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              value={fov}
              onChange={(e) => onFovChange(parseFloat(e.target.value) || 0)}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              min="0"
              step="0.1"
            />
            <select
              value={fovUnit}
              onChange={(e) => onFovUnitChange(e.target.value as Unit)}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="µm">µm</option>
              <option value="nm">nm</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Voltage
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={voltage}
              onChange={(e) => onVoltageChange(parseFloat(e.target.value) || 0)}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              min="0"
              step="0.1"
            />
            <span className="text-sm font-medium text-gray-600">kV</span>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Beam Current
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              value={currentValue}
              onChange={(e) => onCurrentValueChange(parseFloat(e.target.value) || 0)}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              min="0"
              step="0.1"
            />
            <select
              value={currentUnit}
              onChange={(e) => onCurrentUnitChange(e.target.value as CurrentUnit)}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="pA">pA</option>
              <option value="nA">nA</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}
