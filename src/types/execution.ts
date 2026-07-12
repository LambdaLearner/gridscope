/**
 * Shared execution-related types.
 *
 * Single source of truth — imported by App.tsx, ExecutionPanel.tsx,
 * the useCodeExecution hook, and API clients.
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
  a?: number; // alpha tilt
  b?: number; // beta tilt
  sampleType?: string;
  mode?: string;
  voltage_kV?: number;
  current_pA?: number;
  fov_um?: number;
  label?: string;
}
