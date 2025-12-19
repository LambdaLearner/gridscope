import { GridVisualization } from './GridVisualization';
import { JSONConfig } from './JSONConfig';
import { ExperimentConfig } from '../types/config';
import { Clock, Grid3x3, Ruler } from 'lucide-react';

interface PreviewPanelProps {
  config: ExperimentConfig | null;
  totalTiles: number;
  estimatedTime: string;
  stepSize: number;
  overlapPercent: number;
}

export function PreviewPanel({
  config,
  totalTiles,
  estimatedTime,
  stepSize,
  overlapPercent,
}: PreviewPanelProps) {
  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Plan Preview</h2>

        <div className="mb-6">
          <GridVisualization rows={5} cols={5} overlapPercent={overlapPercent} />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
            <div className="flex items-center gap-2 text-blue-700 mb-1">
              <Grid3x3 className="w-4 h-4" />
              <span className="text-xs font-medium">Total Tiles</span>
            </div>
            <div className="text-2xl font-bold text-blue-900">{totalTiles}</div>
          </div>

          <div className="bg-green-50 rounded-lg p-4 border border-green-200">
            <div className="flex items-center gap-2 text-green-700 mb-1">
              <Ruler className="w-4 h-4" />
              <span className="text-xs font-medium">Step Size</span>
            </div>
            <div className="text-2xl font-bold text-green-900">{stepSize.toFixed(1)}<span className="text-sm ml-1">µm</span></div>
          </div>

          <div className="bg-amber-50 rounded-lg p-4 border border-amber-200">
            <div className="flex items-center gap-2 text-amber-700 mb-1">
              <Clock className="w-4 h-4" />
              <span className="text-xs font-medium">Est. Time</span>
            </div>
            <div className="text-2xl font-bold text-amber-900">{estimatedTime}</div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-200">
        <JSONConfig config={config} />
      </div>
    </div>
  );
}
