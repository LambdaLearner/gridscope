/**
 * API client for the STEM Digital Twin
 */

const API_BASE_URL = 'http://localhost:8000/api/microscope';

export interface StagePosition {
  x: number;
  y: number;
  z: number;
  a: number;
  b: number;
  x_um: number;
  y_um: number;
  z_um: number;
}

export interface DetectorSettings {
  size: number;
  exposure: number;
  binning: number;
  field_of_view_um: number;
  noise_sigma: number;
}

export interface BeamSettings {
  x: number;
  y: number;
  current_pA: number;
  voltage_kV: number;
}

export interface DiffractionSettings {
  camera_length_mm: number;
  beamstop_radius_px: number;
}

export interface MicroscopeState {
  stage: {
    x: number;
    y: number;
    z: number;
    a: number;
    b: number;
  };
  beam: BeamSettings;
  vacuum: number;
  status: string;
  holder_type: string;
  detectors: {
    [key: string]: DetectorSettings;
  };
  mode?: string;  // "IMG" or "DIFF"
  sample_type?: string;  // "au_nanoparticles" or "fcc_crystal"
  diffraction?: DiffractionSettings;
  tilt_enabled?: boolean;
}

export interface AcquiredImage {
  image_base64?: string;
  raw_base64?: string;
  width: number;
  height: number;
  dtype: string;
}

export interface AcquireResult {
  success: boolean;
  device: string;
  image: AcquiredImage;
  stage: {
    x_um: number;
    y_um: number;
    z_um: number;
  };
  settings: DetectorSettings;
}

export interface AutofocusResult {
  success: boolean;
  result: {
    best_z_m: number;
    best_z_um_relative: number;
    scores: [number, number][];
  };
  new_z_um: number;
}

/**
 * Check microscope connection status
 */
export async function getMicroscopeStatus(): Promise<{
  connected: boolean;
  host?: string;
  port?: number;
  state?: MicroscopeState;
  error?: string;
}> {
  try {
    const response = await fetch(`${API_BASE_URL}/status`);
    return response.json();
  } catch (error) {
    return { connected: false, error: String(error) };
  }
}

/**
 * Get current microscope state
 */
export async function getMicroscopeState(): Promise<MicroscopeState> {
  const response = await fetch(`${API_BASE_URL}/state`);
  if (!response.ok) {
    throw new Error('Failed to get microscope state');
  }
  return response.json();
}

/**
 * Get current stage position
 */
export async function getStagePosition(): Promise<StagePosition> {
  const response = await fetch(`${API_BASE_URL}/stage`);
  if (!response.ok) {
    throw new Error('Failed to get stage position');
  }
  return response.json();
}

/**
 * Set stage position
 */
export async function setStagePosition(
  position: Partial<{ x: number; y: number; z: number; a: number; b: number }>,
  relative: boolean = true
): Promise<{ success: boolean; new_position: StagePosition }> {
  const response = await fetch(`${API_BASE_URL}/stage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ position, relative }),
  });
  if (!response.ok) {
    throw new Error('Failed to set stage position');
  }
  return response.json();
}

/**
 * Get detector settings
 */
export async function getDetectorSettings(
  device: string = 'haadf'
): Promise<{ device: string; settings: DetectorSettings }> {
  const response = await fetch(`${API_BASE_URL}/detectors/${device}`);
  if (!response.ok) {
    throw new Error('Failed to get detector settings');
  }
  return response.json();
}

/**
 * Set detector settings
 */
export async function setDetectorSettings(
  device: string,
  settings: Partial<DetectorSettings>
): Promise<{ success: boolean; settings: DetectorSettings }> {
  const response = await fetch(`${API_BASE_URL}/detectors/${device}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
  if (!response.ok) {
    throw new Error('Failed to set detector settings');
  }
  return response.json();
}

/**
 * Acquire an image
 */
export async function acquireImage(
  device: string = 'haadf'
): Promise<AcquireResult> {
  const response = await fetch(`${API_BASE_URL}/acquire`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device }),
  });
  if (!response.ok) {
    throw new Error('Failed to acquire image');
  }
  return response.json();
}

/**
 * Run autofocus
 */
export async function runAutofocus(
  device: string = 'haadf',
  z_range_um: number = 2.0,
  z_steps: number = 9
): Promise<AutofocusResult> {
  const response = await fetch(`${API_BASE_URL}/autofocus`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device, z_range_um, z_steps }),
  });
  if (!response.ok) {
    throw new Error('Autofocus failed');
  }
  return response.json();
}

/**
 * Set imaging mode (IMG or DIFF)
 */
export async function setMode(
  mode: 'IMG' | 'DIFF'
): Promise<{ success: boolean; mode: string }> {
  const response = await fetch(`${API_BASE_URL}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: 'set_mode', params: { mode } }),
  });
  if (!response.ok) {
    throw new Error('Failed to set mode');
  }
  return response.json();
}

/**
 * Set sample type
 */
export async function setSampleType(
  sampleType: 'au_nanoparticles' | 'fcc_crystal'
): Promise<{ success: boolean; sample_type: string }> {
  const response = await fetch(`${API_BASE_URL}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: 'set_sample_type', params: { sample_type: sampleType } }),
  });
  if (!response.ok) {
    throw new Error('Failed to set sample type');
  }
  return response.json();
}

/**
 * Set diffraction settings
 */
export async function setDiffractionSettings(
  settings: Partial<DiffractionSettings>
): Promise<{ success: boolean; settings: DiffractionSettings }> {
  const response = await fetch(`${API_BASE_URL}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: 'set_diffraction_settings', params: settings }),
  });
  if (!response.ok) {
    throw new Error('Failed to set diffraction settings');
  }
  return response.json();
}

/**
 * Set beam settings (current, voltage)
 */
export async function setBeamSettings(
  settings: Partial<BeamSettings>
): Promise<{ success: boolean; beam: BeamSettings }> {
  const response = await fetch(`${API_BASE_URL}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: 'set_beam', params: { beam_settings: settings } }),
  });
  if (!response.ok) {
    throw new Error('Failed to set beam settings');
  }
  return response.json();
}

/**
 * Execute a command on the microscope
 */
export async function executeCommand(
  command: string,
  params: Record<string, unknown> = {}
): Promise<{ success: boolean; command: string; result: unknown }> {
  const response = await fetch(`${API_BASE_URL}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, params }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Command execution failed');
  }
  return response.json();
}

/**
 * Start the digital twin server
 */
export async function startDigitalTwinServer(): Promise<{
  status: string;
  port: number;
}> {
  const response = await fetch(`${API_BASE_URL}/start-server`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error('Failed to start digital twin server');
  }
  return response.json();
}

/**
 * Get command log
 */
export async function getCommandLog(
  lastN: number = 50
): Promise<{ log: unknown[]; count: number }> {
  const response = await fetch(`${API_BASE_URL}/log?last_n=${lastN}`);
  if (!response.ok) {
    throw new Error('Failed to get command log');
  }
  return response.json();
}
