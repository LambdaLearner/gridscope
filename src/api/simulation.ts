/**
 * API client for the SIMULATION surface (/api/simulation).
 *
 * Twin-only configuration with no real-instrument counterpart: the sample
 * registry and registration, acquisition conditions (drift, contamination,
 * detector noise, autofocus limits), and specimen reset. Only the Sample
 * Settings window uses this module.
 *
 * There are no environment presets: conditions are explicit numbers, set
 * through the individual setters below and bounded by GET /simulation/limits
 * (see api/limits.ts).
 */

import { apiGet, apiPost } from './client';

// ===== Types =====

/** One entry of a sample's param_schema: how to render a control for it. */
export interface ParamSchemaEntry {
  type: 'int' | 'float' | 'bool' | 'str';
  min?: number;
  max?: number;
  /** For str params with a fixed value set (v3: e.g. zone_axis,
   *  orientation_mode) — render a dropdown, not a text field. */
  choices?: string[];
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
}

export interface RegisterOptions {
  params?: Record<string, unknown>;
  D?: number;
  H?: number;
  W?: number;
  thickness_nm?: number;
  thickness_seed?: number;
}

export interface SpecimenState {
  contamination_enabled: number;
  /** Percentage of the calibrated nominal rate: 100 = nominal, 0 = off. */
  contamination_rate: number;
  max_contamination?: number;
}

export interface DriftState {
  vx_px_per_s: number;
  vy_px_per_s: number;
  accum_x_px: number;
  accum_y_px: number;
  line_jitter_px: number;
  enabled: number;
  max_dt_s: number;
}

export interface NoiseState {
  dwell_us: number;
  dqe: number;
  readout_e: number;
  use_dose_model: number;
  noise_sigma: number;
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
 * reset). Building the volume takes a few seconds for large samples — and
 * the FIRST load of a shape_assembly parameter set also runs a one-off
 * density calibration. Acquisition conditions are independent of
 * registration and unchanged by it.
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

export function getSpecimen(): Promise<SpecimenState> {
  return apiGet('/simulation/specimen');
}

/** Contamination: carbon accumulating where the beam dwells.
 *  `rate` is a percentage — 100 = nominal, 200 = twice as fast, 0 = off. */
export function setContamination(settings: {
  enabled?: boolean;
  rate?: number;
}): Promise<{ success: boolean } & SpecimenState> {
  return apiPost('/simulation/contamination', settings);
}

/** Detector / dose noise. Writes ONLY the keys passed — an omitted key
 *  keeps its current server-side value. */
export function setNoise(settings: {
  dwell_us?: number;
  dqe?: number;
  readout_e?: number;
  use_dose_model?: boolean;
  noise_sigma?: number;
}): Promise<{ success: boolean } & NoiseState> {
  return apiPost('/simulation/noise', settings);
}

/** Peak/floor contrast ratio below which autofocus reports non-convergence. */
export function setAutofocusLimits(settings: {
  min_contrast?: number;
}): Promise<{ success: boolean; af_min_contrast: number }> {
  return apiPost('/simulation/autofocus-limits', settings);
}

export function resetSpecimen(): Promise<{ success: boolean; reset: boolean }> {
  return apiPost('/simulation/specimen/reset');
}

export function getDrift(): Promise<DriftState> {
  return apiGet('/simulation/drift');
}

export function setDrift(settings: {
  /** Physical interface (preferred): realistic stage drift is 0.1–5 nm/s. */
  vx_nm_per_s?: number;
  vy_nm_per_s?: number;
  line_jitter_nm?: number;
  /** Legacy volume-pixel interface. */
  vx_px_per_s?: number;
  vy_px_per_s?: number;
  line_jitter_px?: number;
  /** Per-frame elapsed-time cap (idle-jump guard); raise for a deliberate
   *  long-gap drift study. */
  max_dt_s?: number;
  enabled?: boolean;
  reset_accum?: boolean;
}): Promise<{ success: boolean; drift: DriftState & { vx_nm_per_s: number; vy_nm_per_s: number } }> {
  return apiPost('/simulation/drift', settings);
}
