/**
 * API client for the microscope CONTROL surface (/api/microscope).
 *
 * Everything here has a real-instrument counterpart. Twin-only configuration
 * (samples, environments, degradation) lives in simulation.ts — mirroring the
 * backend's control/simulation split.
 */

import { apiGet, apiPost } from './client';

// ===== Types =====

export interface StageLimits {
  x: number; // metres, symmetric ±
  y: number;
  z: number;
  a: number; // degrees, symmetric ±
  b: number;
}

export interface DetectorSettings {
  size: number;
  exposure: number;
  binning: number;
  field_of_view_um: number;
  magnification: number;
  dwell_us: number;
  noise_sigma: number;
  [key: string]: number;
}

export interface BeamSettings {
  x: number;
  y: number;
  current_pA: number;
  voltage_kV: number;
}

export interface SampleStatus {
  name: string | null;
  registered: boolean;
}

export interface MicroscopeState {
  stage: { x: number; y: number; z: number; a: number; b: number };
  beam: BeamSettings;
  vacuum: number;
  status: string;
  holder_type: string;
  mode: string; // "IMG" | "DIFF"
  detectors: { [device: string]: DetectorSettings };
  diffraction: { [key: string]: number };
  environment: string;
  sample: SampleStatus;
  stage_limits: StageLimits;
}

export interface CommandLogEntry {
  t: number;
  method: string;
  params: Record<string, unknown>;
  result_preview: string;
}

export interface RunStatus {
  active: boolean;
  started_at: number | null;
  label: string | null;
}

export interface SessionSnapshot {
  connected: boolean;
  state?: MicroscopeState;
  sample?: SampleStatus;
  run: RunStatus;
  log?: CommandLogEntry[];
}

export interface StagePositionResult {
  x: number; y: number; z: number; a: number; b: number;
  x_um: number; y_um: number; z_um: number;
}

export interface AcquiredImagePayload {
  image_base64: string;
  width: number;
  height: number;
  dtype: string;
}

export interface AcquireResult {
  success: boolean;
  device: string;
  image: AcquiredImagePayload;
  stage: { x_um: number; y_um: number; z_um: number; a: number; b: number };
  mode: string;
  sample: SampleStatus;
  settings: DetectorSettings;
}

export interface AutofocusResult {
  success: boolean;
  result: {
    converged: boolean;
    reason: string;
    best_z_m: number;
    best_z_um_relative: number;
    curve_contrast: number;
    n_candidate_peaks: number;
    scores: [number, number][];
  };
  new_z_um: number;
}

// ===== Endpoints =====

export function getMicroscopeStatus(): Promise<{
  connected: boolean;
  ready?: boolean;
  sample?: string | null;
  error?: string;
}> {
  return apiGet('/microscope/status');
}

export function getSession(logLastN = 30): Promise<SessionSnapshot> {
  return apiGet(`/microscope/session?log_last_n=${logLastN}`);
}

export function getMicroscopeState(): Promise<MicroscopeState> {
  return apiGet('/microscope/state');
}

export function getStageLimits(): Promise<{ limits: StageLimits }> {
  return apiGet('/microscope/limits');
}

export function getStagePosition(): Promise<StagePositionResult> {
  return apiGet('/microscope/stage');
}

/**
 * Move the stage. Throws ApiError(400) with the twin's violation message when
 * the move is rejected by the soft limits — the stage does not move.
 */
export function setStagePosition(
  position: Partial<{ x: number; y: number; z: number; a: number; b: number }>,
  relative = true,
): Promise<{ success: boolean; new_position: StagePositionResult }> {
  return apiPost('/microscope/stage', { position, relative });
}

export function setDetectorSettings(
  device: string,
  settings: Partial<DetectorSettings>,
): Promise<{ success: boolean; settings: DetectorSettings }> {
  return apiPost(`/microscope/detectors/${device}`, settings);
}

export function setMagnification(
  magnification: number,
  device = 'haadf',
): Promise<{ success: boolean; magnification: number; field_of_view_um: number }> {
  return apiPost('/microscope/magnification', { magnification, device });
}

export function acquireImage(device = 'haadf'): Promise<AcquireResult> {
  return apiPost('/microscope/acquire', { device });
}

export function runAutofocus(
  device = 'haadf',
  z_range_um = 2.0,
  z_steps = 9,
): Promise<AutofocusResult> {
  return apiPost('/microscope/autofocus', { device, z_range_um, z_steps });
}

export function setMode(mode: 'IMG' | 'DIFF'): Promise<{ success: boolean; mode: string }> {
  return apiPost('/microscope/mode', { mode });
}

export function setBeamSettings(
  settings: Partial<BeamSettings>,
  relative = false,
): Promise<{ success: boolean; new_beam: BeamSettings }> {
  return apiPost('/microscope/beam', { settings, relative });
}

export function startDigitalTwinServer(): Promise<{ status: string; port: number }> {
  return apiPost('/microscope/start-server');
}
