import { ExperimentConfig, TilePosition } from '../types/config';

export function calculateStepSize(fov: number, overlapPercent: number): number {
  const overlapFactor = 1 - overlapPercent / 100;
  return fov * overlapFactor;
}

export function generateTilePositions(
  startX: number,
  startY: number,
  stepSize: number,
  rows: number,
  cols: number
): TilePosition[] {
  const tiles: TilePosition[] = [];
  let index = 0;

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      tiles.push({
        tile_index: index,
        row,
        col,
        x: startX + col * stepSize,
        y: startY + row * stepSize,
      });
      index++;
    }
  }

  return tiles;
}

export function estimateTotalTime(
  tileCount: number,
  dwellTime: number,
  hasAutofocus: boolean,
  hasAberrationCorrection: boolean
): number {
  const autofocusTime = hasAutofocus ? 2 : 0;
  const aberrationTime = hasAberrationCorrection ? 5 : 0;
  const setupTime = 0.5;

  return tileCount * (dwellTime + autofocusTime + aberrationTime + setupTime);
}

export function formatTime(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (minutes < 60) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}
