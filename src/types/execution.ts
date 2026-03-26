/**
 * Shared execution-related types.
 *
 * Single source of truth — imported by App.tsx, ExecutionPanel.tsx,
 * useCodeExecution hook, and API clients.
 */

export interface ExecutionLog {
  id: string;
  type: 'info' | 'success' | 'error' | 'image' | 'stage' | 'command';
  message: string;
  timestamp: Date;
  data?: {
    image_base64?: string;
    stage?: { x_um: number; y_um: number; z_um: number; a?: number; b?: number };
    command?: string;
    sampleType?: string;
    mode?: string;
    voltage_kV?: number;
    current_pA?: number;
    fov_um?: number;
  };
}

export interface AcquiredImage {
  image_base64: string;
  x_um: number;
  y_um: number;
  z_um?: number;
  a?: number;  // alpha tilt
  b?: number;  // beta tilt
  sampleType?: string;
  mode?: string;
  voltage_kV?: number;
  current_pA?: number;
  fov_um?: number;
}

// --- Structured execution plan types (Phase 3) ---

export interface ExecutionStep {
  action: string;
  params: Record<string, unknown>;
  description: string;
}

export interface ExecutionPlan {
  plan_type: string;
  steps: ExecutionStep[];
  summary: string;
}
