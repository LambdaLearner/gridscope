/**
 * API client for executing code on the STEM Digital Twin
 */

const API_BASE_URL = 'http://localhost:8000/api/execute';

export interface ExecuteOperation {
  operation: string;
  params?: Record<string, unknown>;
}

export interface ExecuteResult {
  operation: string;
  success: boolean;
  error?: string;
  image?: {
    image_base64: string;
    width: number;
    height: number;
  };
  stage?: {
    x_um: number;
    y_um: number;
    z_um: number;
  };
  result?: unknown;
  settings?: unknown;
  state?: unknown;
}

export interface SimpleExecuteParams {
  action: 'acquire' | 'move' | 'autofocus' | 'scan_grid';
  params?: Record<string, unknown>;
}

export interface AcquireResult {
  success: boolean;
  action: string;
  image?: {
    image_base64: string;
    width: number;
    height: number;
  };
  stage?: {
    x_um: number;
    y_um: number;
    z_um: number;
  };
}

export interface MoveResult {
  success: boolean;
  action: string;
  stage: {
    x_um: number;
    y_um: number;
    z_um: number;
  };
}

export interface AutofocusResult {
  success: boolean;
  action: string;
  result: {
    best_z_m: number;
    best_z_um_relative: number;
    scores: [number, number][];
  };
}

export interface ScanGridResult {
  success: boolean;
  action: string;
  images: {
    tile_index: number;
    x_um: number;
    y_um: number;
    image: {
      image_base64: string;
      width: number;
      height: number;
    };
  }[];
  logs: string[];
  total_tiles: number;
}

/**
 * Execute a sequence of operations
 */
export async function executeOperations(
  operations: ExecuteOperation[]
): Promise<{ results: ExecuteResult[] }> {
  const response = await fetch(`${API_BASE_URL}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operations }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Execution failed');
  }

  return response.json();
}

/**
 * Execute a simple action
 */
export async function executeSimple<T = unknown>(
  action: SimpleExecuteParams['action'],
  params: Record<string, unknown> = {}
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/simple`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, params }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Execution failed');
  }

  return response.json();
}

/**
 * Acquire a single image
 */
export async function acquireImage(fov_um?: number): Promise<AcquireResult> {
  return executeSimple('acquire', fov_um ? { fov_um } : {});
}

/**
 * Move the stage
 */
export async function moveStage(
  x_um: number,
  y_um: number,
  relative: boolean = true
): Promise<MoveResult> {
  return executeSimple('move', { x_um, y_um, relative });
}

/**
 * Run autofocus
 */
export async function runAutofocus(
  z_range_um: number = 4.0,
  z_steps: number = 9
): Promise<AutofocusResult> {
  return executeSimple('autofocus', { z_range_um, z_steps });
}

/**
 * Scan a grid
 */
export async function scanGrid(params: {
  rows: number;
  cols: number;
  step_um: number;
  start_x_um?: number;
  start_y_um?: number;
  autofocus?: boolean;
  fov_um?: number;
}): Promise<ScanGridResult> {
  return executeSimple('scan_grid', params);
}

