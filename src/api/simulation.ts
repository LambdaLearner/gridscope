/**
 * API client for the SIMULATION surface (/api/simulation).
 *
 * Twin-only configuration with no real-instrument counterpart: the sample
 * registry and registration, simulation environments, specimen degradation,
 * and drift injection. Only the Sample Settings window uses this module.
 */

import { apiGet, apiPost } from './client';

// ===== Types =====

/** One entry of a sample's param_schema: how to render a control for it. */
export interface ParamSchemaEntry {
  type: 'int' | 'float' | 'bool' | 'str';
  min?: number;
  max?: number;
}

export interface SampleInfo {
  name: string;
  display_name: string;
  description: string;
  default_params: Record<string, unknown>;
  param_schema: Record<string, ParamSchemaEntry>;
}

export interface ThicknessInfo {
  total_nm: number;
  working_nm: number;
  z_start_nm: number;
  seed: number;
}

export interface CurrentSample {
  name: string | null;
  params: Record<string, unknown> | null;
  crystalline: boolean;
}

export interface RegisterResult {
  success: boolean;
  registered: string;
  shape: number[];
  params: Record<string, unknown>;
  thickness: ThicknessInfo | null;
  environment: string | null;
}

export interface RegisterOptions {
  params?: Record<string, unknown>;
  environment?: string;
  D?: number;
  H?: number;
  W?: number;
  thickness_nm?: number;
  thickness_seed?: number;
}

export interface AbtemAvailability {
  available: boolean;
  detail: string | null;
}

export interface AbtemResult {
  success: boolean;
  engine: 'abtem';
  image: { image_base64: string; width: number; height: number; dtype: string };
  state: {
    sample: string;
    params: Record<string, unknown>;
    tilt_a_deg: number;
    tilt_b_deg: number;
    energy_kev: number;
    num_frozen_phonons: number;
  };
  fingerprint: string;
  n_atoms: number;
  compute_seconds: number;
  cached: boolean;
}

export interface EnvironmentInfo {
  environment: string;
  available: string[];
}

export interface SpecimenState {
  beam_damage_enabled: number;
  damage_dose_threshold: number;
  damage_rate: number;
  contamination_enabled: number;
  contamination_rate: number;
  max_accumulated_dose?: number;
  max_contamination?: number;
  [key: string]: number | undefined;
}

export interface DriftState {
  vx_px_per_s: number;
  vy_px_per_s: number;
  accum_x_px: number;
  accum_y_px: number;
  line_jitter_px: number;
  enabled: number;
}

// ===== Endpoints =====

export function listSamples(): Promise<{ samples: SampleInfo[]; count: number }> {
  return apiGet('/simulation/samples');
}

export function getCurrentSample(): Promise<{ sample: CurrentSample; registered: boolean }> {
  return apiGet('/simulation/sample');
}

/**
 * Register a sample: it becomes the active specimen (degradation history is
 * reset). Building the volume takes a few seconds for large samples.
 */
export function registerSample(
  name: string,
  options: RegisterOptions = {},
): Promise<RegisterResult> {
  const { params = {}, ...rest } = options;
  return apiPost('/simulation/sample/register', { name, params, ...rest });
}

export function getThickness(): Promise<ThicknessInfo> {
  return apiGet('/simulation/thickness');
}

/**
 * Re-pick the working thickness / seed without regenerating the sample
 * (simulates navigating to a differently-thick region). 409 if no sample.
 */
export function setThickness(settings: {
  thickness_nm?: number;
  thickness_seed?: number;
}): Promise<{ success: boolean } & ThicknessInfo> {
  return apiPost('/simulation/thickness', settings);
}

export function getAbtemAvailability(): Promise<AbtemAvailability> {
  return apiGet('/simulation/diffraction/abtem/availability');
}

/**
 * Compute a dynamical (abTEM multislice) SAED pattern for the registered
 * sample at the current stage tilt. Long-running (seconds to tens of
 * seconds); 409 while another computation runs; 501 if abtem not installed.
 */
export function computeAbtemDiffraction(options: {
  num_frozen_phonons?: number;
} = {}): Promise<AbtemResult> {
  return apiPost('/simulation/diffraction/abtem', options);
}

export function setSpecimen(settings: {
  beam_damage_enabled?: boolean;
  damage_dose_threshold?: number;
  damage_rate?: number;
  contamination_enabled?: boolean;
  contamination_rate?: number;
}): Promise<{ success: boolean } & SpecimenState> {
  return apiPost('/simulation/specimen', settings);
}

export function getEnvironment(): Promise<EnvironmentInfo> {
  return apiGet('/simulation/environment');
}

export function setEnvironment(name: string): Promise<{ success: boolean; environment: string }> {
  return apiPost('/simulation/environment', { name });
}

export function getSpecimen(): Promise<SpecimenState> {
  return apiGet('/simulation/specimen');
}

export function resetSpecimen(): Promise<{ success: boolean; reset: boolean }> {
  return apiPost('/simulation/specimen/reset');
}

export function getDrift(): Promise<DriftState> {
  return apiGet('/simulation/drift');
}

export function setDrift(settings: {
  vx_px_per_s?: number;
  vy_px_per_s?: number;
  line_jitter_px?: number;
  enabled?: boolean;
  reset_accum?: boolean;
}): Promise<{ success: boolean; drift: DriftState }> {
  return apiPost('/simulation/drift', settings);
}
