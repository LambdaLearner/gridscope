export type Unit = 'µm' | 'nm';
export type CurrentUnit = 'pA' | 'nA';

export interface StagePosition {
  x: number;
  y: number;
}

export interface GridConfig {
  rows: number;
  cols: number;
  overlap_percent: number;
  step_size: number;
}

export interface TilePosition extends StagePosition {
  tile_index: number;
  row: number;
  col: number;
}

export interface ExperimentConfig {
  fov: number;
  fov_unit: Unit;
  voltage_kv: number;
  current_value: number;
  current_unit: CurrentUnit;
  grid: GridConfig;
  start_pos: StagePosition;
  autofocus_each_tile: boolean;
  auto_aberration_each_tile: boolean;
  dwell_s: number;
  tiles: TilePosition[];
}
