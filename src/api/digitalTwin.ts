/**
 * API client for the microscope CONTROL surface (/api/microscope).
 *
 * Everything here has a real-instrument counterpart. Twin-only configuration
 * (samples, environments, degradation) lives in simulation.ts — mirroring the
 * backend's control/simulation split.
 */

import { apiGet, apiPost } from './client';

// Magnification <-> field-of-view calibration: mag = MAG_K / fov_metres.
// Same constant as the twin server (57 kx <-> 1.6564523008 µm).
export const MAG_K = 0.0944177811456;

export function fovUmToMag(fovUm: number): number {
  return MAG_K / (fovUm * 1e-6);
}

export function magToFovUm(mag: number): number {
  return (MAG_K / mag) * 1e6;
}

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

export interface ThicknessState {
  total_nm: number;
  working_nm: number;
  z_start_nm: number;
  seed: number;
}

export interface ResolutionInfo {
  resolution_px: number;
  allowed: number[];
}

export interface MicroscopeState {
  stage: { x: number; y: number; z: number; a: number; b: number };
  beam: BeamSettings;
  vacuum: number;
  status: string;
  holder_type: string;
  mode: string; // "IMG" | "DIFF" | "EELS"
  detectors: { [device: string]: DetectorSettings };
  diffraction: { [key: string]: number };
  environment: string;
  sample: SampleStatus;
  stage_limits: StageLimits;
  thickness?: ThicknessState;
  resolution?: ResolutionInfo;
}

export interface SpectrumEdge {
  label: string;
  onset_ev: number;
  Z: number;
}

export interface SpectrumResult {
  success: boolean;
  energy_ev: number[];
  intensity: number[];
  edges: SpectrumEdge[];
  zlp_ev: number;
  plasmon_ev: number;
  thickness_nm: number;
  elements_Z: number[];
}

export interface DiffractionSettingsInfo {
  camera_length_mm: number;
  beamstop_radius_px: number;
  thickness_nm: number;
  aperture_um: number;
  depth_nm: number;
  use_local_atoms: number;
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

export function setMode(mode: 'IMG' | 'DIFF' | 'EELS'): Promise<{ success: boolean; mode: string }> {
  return apiPost('/microscope/mode', { mode });
}

export function getResolution(device = 'haadf'): Promise<ResolutionInfo> {
  return apiGet(`/microscope/resolution?device=${device}`);
}

/** resolution_px must be one of 512/1024/2048; 2048 frames can take ~30 s. */
export function setResolution(
  resolution_px: number,
  device = 'haadf',
): Promise<{ success: boolean } & ResolutionInfo> {
  return apiPost('/microscope/resolution', { resolution_px, device });
}

/** Single-spot EELS spectrum (structured dummy on the twin). */
export function acquireSpectrum(options: {
  ev_min?: number;
  ev_max?: number;
  n_channels?: number;
} = {}): Promise<SpectrumResult> {
  return apiPost('/microscope/spectrum', options);
}

export function getDiffractionSettings(): Promise<DiffractionSettingsInfo> {
  return apiGet('/microscope/diffraction');
}

export function setDiffractionSettings(settings: {
  camera_length_mm?: number;
  beamstop_radius_px?: number;
  aperture_um?: number;
  depth_nm?: number;
}): Promise<{ success: boolean } & DiffractionSettingsInfo> {
  return apiPost('/microscope/diffraction', settings);
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
