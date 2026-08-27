/**
 * Session seeds strip contract tests: the v2 conditions blob (Copy builds it
 * from session state, Load re-applies it verbatim), rejection of preset-era
 * v1 blobs, and the live conditions chip.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SessionSeedsStrip } from '../SessionSeedsStrip';
import type { MicroscopeState, SessionSnapshot } from '../../api/digitalTwin';
import * as simulation from '../../api/simulation';

vi.mock('../../api/simulation', () => ({
  getCurrentSample: vi.fn(),
  registerSample: vi.fn(),
  setDrift: vi.fn(),
  setContamination: vi.fn(),
  setNoise: vi.fn(),
  setAutofocusLimits: vi.fn(),
}));

const writeText = vi.fn();
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText },
  configurable: true,
});

const BASE_STATE: MicroscopeState = {
  stage: { x: 0, y: 0, z: 0, a: 0, b: 0 },
  beam: { x: 0, y: 0, current_pA: 50, voltage_kV: 200 },
  vacuum: 1e-6,
  status: 'Idle',
  holder_type: 'DoubleTilt',
  mode: 'IMG',
  detectors: {
    haadf: {
      size: 256, exposure: 0.1, binning: 1, field_of_view_um: 20,
      magnification: 4720, dwell_us: 42, noise_sigma: 12,
      dqe: 0.5, readout_e: 2, use_dose_model: 1,
    },
  },
  diffraction: {},
  sample: { name: 'fcc_single_crystal', registered: true },
  stage_limits: { x: 1.5e-3, y: 1.5e-3, z: 1e-3, a: 30, b: 30 },
  thickness: { total_nm: 100, working_nm: 80, z_start_nm: 3.2, seed: 7 },
  drift: {
    vx_px_per_s: 0, vy_px_per_s: 0, vx_nm_per_s: 0.5, vy_nm_per_s: 0.3,
    line_jitter_nm: 0.05, accum_x_px: 0, accum_y_px: 0, line_jitter_px: 0,
    enabled: 1, max_dt_s: 2,
  },
  specimen: { contamination_enabled: 1, contamination_rate: 250, max_contamination: 0 },
  autofocus: { min_contrast: 0.2 },
};

function sessionWithState(overrides: Partial<MicroscopeState> = {}): SessionSnapshot {
  return {
    connected: true,
    sample: { name: 'fcc_single_crystal', registered: true },
    run: { active: false, started_at: null, label: null },
    state: { ...BASE_STATE, ...overrides },
    log: [],
  };
}

const V2_BLOB = {
  version: 2,
  sample: 'amorphous_film',
  params: { seed: 4 },
  thickness_nm: 60,
  thickness_seed: 9,
  conditions: {
    drift: { enabled: true, vx_nm_per_s: 1.2, vy_nm_per_s: 0.4, line_jitter_nm: 0.1, max_dt_s: 10 },
    contamination: { enabled: true, rate: 150 },
    noise: { dwell_us: 33, dqe: 0.6, readout_e: 2.5, use_dose_model: false },
    autofocus: { min_contrast: 0.15 },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  writeText.mockResolvedValue(undefined);
  vi.mocked(simulation.getCurrentSample).mockResolvedValue({
    sample: { name: 'fcc_single_crystal', params: { seed: 11 }, crystalline: true },
    registered: true,
  });
  vi.mocked(simulation.registerSample).mockResolvedValue({
    success: true,
    registered: 'amorphous_film',
    shape: [16, 96, 96],
    params: { seed: 4 },
    thickness: { total_nm: 100, working_nm: 60, z_start_nm: 0, seed: 9 },
  });
  vi.mocked(simulation.setDrift).mockResolvedValue({
    success: true,
    drift: {
      vx_px_per_s: 0, vy_px_per_s: 0, accum_x_px: 0, accum_y_px: 0,
      line_jitter_px: 0, enabled: 1, max_dt_s: 10,
      vx_nm_per_s: 1.2, vy_nm_per_s: 0.4,
    },
  });
  vi.mocked(simulation.setContamination).mockResolvedValue({
    success: true, contamination_enabled: 1, contamination_rate: 150,
  } as Awaited<ReturnType<typeof simulation.setContamination>>);
  vi.mocked(simulation.setNoise).mockResolvedValue({
    success: true, dwell_us: 33, dqe: 0.6, readout_e: 2.5, use_dose_model: 0, noise_sigma: 0,
  });
  vi.mocked(simulation.setAutofocusLimits).mockResolvedValue({
    success: true, af_min_contrast: 0.15,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SessionSeedsStrip — conditions chip', () => {
  it('shows the live drift rates when drift is enabled', () => {
    render(<SessionSeedsStrip session={sessionWithState()} />);
    const chip = screen.getByTestId('seeds-conditions').textContent!;
    expect(chip).toContain('drift 0.5/0.3 nm/s');
    expect(chip).toContain('contam 250%');
  });

  it('shows off markers when drift and contamination are disabled', () => {
    render(
      <SessionSeedsStrip
        session={sessionWithState({
          drift: { ...BASE_STATE.drift!, enabled: 0 },
          specimen: { contamination_enabled: 0, contamination_rate: 100, max_contamination: 0 },
        })}
      />,
    );
    const chip = screen.getByTestId('seeds-conditions').textContent!;
    expect(chip).toContain('drift off');
    expect(chip).toContain('contam off');
  });
});

describe('SessionSeedsStrip — Copy', () => {
  it('writes a v2 blob with the exact condition values from the session state', async () => {
    render(<SessionSeedsStrip session={sessionWithState()} />);
    fireEvent.click(screen.getByRole('button', { name: /Copy/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const blob = JSON.parse(writeText.mock.calls[0][0] as string);
    expect(blob).toEqual({
      version: 2,
      sample: 'fcc_single_crystal',
      params: { seed: 11 },
      thickness_nm: 80,
      thickness_seed: 7,
      conditions: {
        drift: {
          enabled: true, vx_nm_per_s: 0.5, vy_nm_per_s: 0.3,
          line_jitter_nm: 0.05, max_dt_s: 2,
        },
        contamination: { enabled: true, rate: 250 },
        noise: { dwell_us: 42, dqe: 0.5, readout_e: 2, use_dose_model: true },
        autofocus: { min_contrast: 0.2 },
      },
    });
  });
});

describe('SessionSeedsStrip — Load', () => {
  it('re-applies a v2 blob: register, then drift (+reset), contamination, noise, autofocus', async () => {
    const onApplied = vi.fn();
    vi.spyOn(window, 'prompt').mockReturnValue(JSON.stringify(V2_BLOB));
    render(<SessionSeedsStrip session={sessionWithState()} onApplied={onApplied} />);
    fireEvent.click(screen.getByRole('button', { name: /Load/i }));
    await waitFor(() => {
      expect(simulation.registerSample).toHaveBeenCalledWith('amorphous_film', {
        params: { seed: 4 },
        thickness_nm: 60,
        thickness_seed: 9,
      });
      expect(simulation.setDrift).toHaveBeenCalledWith({
        enabled: true, vx_nm_per_s: 1.2, vy_nm_per_s: 0.4,
        line_jitter_nm: 0.1, max_dt_s: 10, reset_accum: true,
      });
      expect(simulation.setContamination).toHaveBeenCalledWith({ enabled: true, rate: 150 });
      expect(simulation.setNoise).toHaveBeenCalledWith({
        dwell_us: 33, dqe: 0.6, readout_e: 2.5, use_dose_model: false,
      });
      expect(simulation.setAutofocusLimits).toHaveBeenCalledWith({ min_contrast: 0.15 });
      expect(onApplied).toHaveBeenCalled();
    });
    expect(screen.getByText(/Re-applied 'amorphous_film'/)).toBeTruthy();
  });

  it('rejects a preset-era (v1) blob without touching the server', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue(
      JSON.stringify({
        sample: 'fcc_single_crystal',
        params: {},
        thickness_nm: 100,
        thickness_seed: 0,
        environment: 'pristine',
      }),
    );
    render(<SessionSeedsStrip session={sessionWithState()} />);
    fireEvent.click(screen.getByRole('button', { name: /Load/i }));
    await waitFor(() => {
      expect(screen.getByText(/preset-era \(v1\) blob/)).toBeTruthy();
    });
    expect(screen.getByText(/no longer exist/)).toBeTruthy();
    expect(simulation.registerSample).not.toHaveBeenCalled();
    expect(simulation.setDrift).not.toHaveBeenCalled();
    expect(simulation.setContamination).not.toHaveBeenCalled();
    expect(simulation.setNoise).not.toHaveBeenCalled();
    expect(simulation.setAutofocusLimits).not.toHaveBeenCalled();
  });
});
