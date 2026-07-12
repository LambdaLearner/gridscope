/**
 * API client for the SIMULATION surface (/api/simulation).
 *
 * Twin-only configuration with no real-instrument counterpart: the sample
 * registry and registration, simulation environments, specimen degradation,
 * and drift injection. Only the Sample Settings window uses this module.
 */

import { apiGet, apiPost } from './client';

// ===== Types =====

export interface SampleInfo {
  name: string;
  display_name: string;
  description: string;
  default_params: Record<string, unknown>;
  param_schema: Record<string, unknown>;
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
  environment: string | null;
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
  params: Record<string, unknown> = {},
  environment?: string,
): Promise<RegisterResult> {
  return apiPost('/simulation/sample/register', { name, params, environment });
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
