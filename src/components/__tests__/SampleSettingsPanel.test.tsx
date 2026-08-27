/**
 * Sample Settings window contract tests: registry-driven rendering,
 * the registration gate messaging, run-lock disabling, and the always-visible
 * acquisition-conditions section (server-published limits, clamping, and
 * hydration from session state).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SampleSettingsPanel } from '../SampleSettingsPanel';
import type { MicroscopeState, SessionSnapshot } from '../../api/digitalTwin';
import * as simulation from '../../api/simulation';
import * as twin from '../../api/digitalTwin';
import * as limits from '../../api/limits';
import { FALLBACK_LIMITS, type ConditionLimits } from '../../api/limits';

vi.mock('../../api/simulation', () => ({
  listSamples: vi.fn(),
  registerSample: vi.fn(),
  resetSpecimen: vi.fn(),
  setThickness: vi.fn(),
  setDrift: vi.fn(),
  setContamination: vi.fn(),
  setNoise: vi.fn(),
  setAutofocusLimits: vi.fn(),
}));

vi.mock('../../api/digitalTwin', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/digitalTwin')>();
  return { ...original, setDetectorSettings: vi.fn() };
});

vi.mock('../../api/limits', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/limits')>();
  return { ...original, fetchLimits: vi.fn() };
});

const REGISTRY = {
  samples: [
    {
      name: 'fcc_single_crystal',
      display_name: 'FCC single crystal',
      description: 'Aluminium-like FCC lattice.',
      default_params: {},
      param_schema: {},
    },
    {
      name: 'amorphous_film',
      display_name: 'Amorphous film',
      description: 'Random close packing; diffuse rings.',
      default_params: {},
      param_schema: {},
    },
  ],
  count: 2,
};

const SERVED_LIMITS: ConditionLimits = {
  ...FALLBACK_LIMITS,
  drift: { ...FALLBACK_LIMITS.drift, vx_nm_per_s: { min: 0, max: 7 } },
  contamination: { rate: { min: 0, max: 300 } },
};

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
      magnification: 4720, dwell_us: 20, noise_sigma: 12,
      dqe: 0.8, readout_e: 1.5, use_dose_model: 1,
    },
  },
  diffraction: {},
  sample: { name: 'fcc_single_crystal', registered: true },
  stage_limits: { x: 1.5e-3, y: 1.5e-3, z: 1e-3, a: 30, b: 30 },
  thickness: { total_nm: 100, working_nm: 100, z_start_nm: 0, seed: 0 },
  drift: {
    vx_px_per_s: 0, vy_px_per_s: 0, vx_nm_per_s: 0.5, vy_nm_per_s: 0.5,
    line_jitter_nm: 0.05, accum_x_px: 0, accum_y_px: 0, line_jitter_px: 0,
    enabled: 0, max_dt_s: 2,
  },
  specimen: { contamination_enabled: 0, contamination_rate: 100, max_contamination: 0 },
  autofocus: { min_contrast: 0.08 },
};

function sessionWith(sample: { name: string | null; registered: boolean }): SessionSnapshot {
  return {
    connected: true,
    sample,
    run: { active: false, started_at: null, label: null },
    state: undefined,
    log: [],
  };
}

function sessionWithState(overrides: Partial<MicroscopeState> = {}): SessionSnapshot {
  return {
    connected: true,
    sample: { name: 'fcc_single_crystal', registered: true },
    run: { active: false, started_at: null, label: null },
    state: { ...BASE_STATE, ...overrides },
    log: [],
  };
}

const slider = (label: string | RegExp) => screen.getByLabelText(label) as HTMLInputElement;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(simulation.listSamples).mockResolvedValue(REGISTRY);
  vi.mocked(simulation.registerSample).mockResolvedValue({
    success: true,
    registered: 'fcc_single_crystal',
    shape: [16, 96, 96],
    params: {},
    thickness: { total_nm: 100, working_nm: 100, z_start_nm: 0, seed: 0 },
  });
  vi.mocked(limits.fetchLimits).mockResolvedValue(FALLBACK_LIMITS);
  vi.mocked(simulation.setDrift).mockResolvedValue({
    success: true,
    drift: {
      vx_px_per_s: 0, vy_px_per_s: 0, accum_x_px: 0, accum_y_px: 0,
      line_jitter_px: 0, enabled: 1, max_dt_s: 2,
      vx_nm_per_s: 0.5, vy_nm_per_s: 0.5,
    },
  });
  vi.mocked(simulation.setContamination).mockResolvedValue({
    success: true, contamination_enabled: 1, contamination_rate: 100,
  } as Awaited<ReturnType<typeof simulation.setContamination>>);
  vi.mocked(simulation.setNoise).mockResolvedValue({
    success: true, dwell_us: 20, dqe: 0.8, readout_e: 1.5, use_dose_model: 1, noise_sigma: 0,
  });
  vi.mocked(simulation.setAutofocusLimits).mockResolvedValue({
    success: true, af_min_contrast: 0.08,
  });
});

describe('SampleSettingsPanel', () => {
  it('renders the registry from the server (registry-driven, no hardcoding)', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: null, registered: false })}
        runActive={false}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText('FCC single crystal')).toBeTruthy();
      expect(screen.getByText('Amorphous film')).toBeTruthy();
    });
    expect(screen.getByText(/2 available/)).toBeTruthy();
  });

  it('shows the registration gate message when no sample is registered', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: null, registered: false })}
        runActive={false}
      />,
    );
    expect(screen.getByText(/No sample registered/)).toBeTruthy();
  });

  it('shows the registered sample when one is active', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: 'au_dispersed', registered: true })}
        runActive={false}
      />,
    );
    expect(screen.getByText(/Registered:/)).toBeTruthy();
    expect(screen.getByText('au_dispersed')).toBeTruthy();
  });

  it('registers the selected sample without any environment coupling', async () => {
    const onRegistered = vi.fn();
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: null, registered: false })}
        runActive={false}
        onRegistered={onRegistered}
      />,
    );
    await waitFor(() => expect(screen.getByText('FCC single crystal')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /Register \/ Load sample/i }));
    await waitFor(() => {
      expect(simulation.registerSample).toHaveBeenCalledWith(
        'fcc_single_crystal',
        expect.objectContaining({
          params: {},
          thickness_nm: 100,
          thickness_seed: 0,
        }),
      );
      expect(simulation.registerSample).toHaveBeenCalledWith(
        'fcc_single_crystal',
        expect.not.objectContaining({ environment: expect.anything() }),
      );
      expect(onRegistered).toHaveBeenCalled();
    });
  });

  it('surfaces registration failures from the server', async () => {
    vi.mocked(simulation.registerSample).mockRejectedValue(
      Object.assign(new Error("Atomsk file not found: 'sample_data/polycrystal.xyz'"), {
        name: 'ApiError',
      }),
    );
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: null, registered: false })}
        runActive={false}
      />,
    );
    await waitFor(() => expect(screen.getByText('FCC single crystal')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Register \/ Load sample/i }));
    await waitFor(() => {
      expect(screen.getByText(/Registration failed|file not found/)).toBeTruthy();
    });
  });

  it('locks settings while a script run is active', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: 'fcc_single_crystal', registered: true })}
        runActive={true}
      />,
    );
    await waitFor(() => expect(screen.getByText('FCC single crystal')).toBeTruthy());
    const button = screen.getByRole('button', { name: /Register new sample/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/locked while a script run/)).toBeTruthy();
  });
});

describe('SampleSettingsPanel — acquisition conditions (preset removal)', () => {
  it('renders the condition groups with no environment preset dropdown', async () => {
    const { container } = render(
      <SampleSettingsPanel session={sessionWithState()} runActive={false} />,
    );
    expect(screen.getByText('Sample Registration & Conditions')).toBeTruthy();
    expect(screen.getByText('Mechanical drift')).toBeTruthy();
    expect(screen.getByText('Contamination')).toBeTruthy();
    expect(screen.getByText('Detector noise & dose')).toBeTruthy();
    expect(screen.getByText('Autofocus')).toBeTruthy();
    expect(screen.queryByText(/pristine/i)).toBeNull();
    const options = Array.from(container.querySelectorAll('option')).map((o) => o.textContent);
    expect(options).not.toContain('pristine');
    await waitFor(() => expect(limits.fetchLimits).toHaveBeenCalled());
  });

  it('fetches /simulation/limits on connect and uses the served bounds for the sliders', async () => {
    vi.mocked(limits.fetchLimits).mockResolvedValue(SERVED_LIMITS);
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: null, registered: false })}
        runActive={false}
      />,
    );
    await waitFor(() => expect(slider('Drift vx').max).toBe('7'));
    expect(limits.fetchLimits).toHaveBeenCalledTimes(1);
  });

  it('falls back to FALLBACK_LIMITS when the limits fetch fails', async () => {
    vi.mocked(limits.fetchLimits).mockRejectedValue(new Error('backend offline'));
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: null, registered: false })}
        runActive={false}
      />,
    );
    await waitFor(() => expect(limits.fetchLimits).toHaveBeenCalled());
    expect(slider('Drift vx').max).toBe('50');
    expect(slider(/Rate \(% of nominal/).max).toBe('1000');
  });

  // A range input clamps out-of-range change events natively, so the only
  // honest way to drive an over-bound value through the UI is hydration: the
  // server state carries rate 900 while the served limit caps it at 300.
  it('clamps a hydrated out-of-bound value before the RPC', async () => {
    vi.mocked(limits.fetchLimits).mockResolvedValue(SERVED_LIMITS);
    render(
      <SampleSettingsPanel
        session={sessionWithState({
          specimen: { contamination_enabled: 1, contamination_rate: 900, max_contamination: 0 },
        })}
        runActive={false}
      />,
    );
    await waitFor(() => expect(slider('Drift vx').max).toBe('7'));
    fireEvent.mouseUp(slider(/Rate \(% of nominal/));
    await waitFor(() => {
      expect(simulation.setContamination).toHaveBeenCalledWith({ enabled: true, rate: 300 });
    });
  });

  it('applies contamination on checkbox toggle with the clamped current rate', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: 'fcc_single_crystal', registered: true })}
        runActive={false}
      />,
    );
    fireEvent.click(screen.getByLabelText('Contamination'));
    await waitFor(() => {
      expect(simulation.setContamination).toHaveBeenCalledWith({ enabled: true, rate: 100 });
    });
  });

  it('routes a dwell commit through setNoise only, never setDetectorSettings', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: 'fcc_single_crystal', registered: true })}
        runActive={false}
      />,
    );
    const dwell = slider(/Dwell time/);
    fireEvent.change(dwell, { target: { value: '55' } });
    fireEvent.mouseUp(dwell);
    await waitFor(() => {
      expect(simulation.setNoise).toHaveBeenCalledWith({
        dwell_us: 55, dqe: 0.8, readout_e: 1.5, use_dose_model: true,
      });
    });
    expect(twin.setDetectorSettings).not.toHaveBeenCalled();
  });

  it('commits the autofocus min-contrast slider via setAutofocusLimits', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWith({ name: 'fcc_single_crystal', registered: true })}
        runActive={false}
      />,
    );
    const af = slider(/Min contrast for convergence/);
    fireEvent.change(af, { target: { value: '0.3' } });
    fireEvent.mouseUp(af);
    await waitFor(() => {
      expect(simulation.setAutofocusLimits).toHaveBeenCalledWith({ min_contrast: 0.3 });
    });
  });

  it('hydrates every condition widget from the session state', async () => {
    render(
      <SampleSettingsPanel
        session={sessionWithState({
          drift: {
            ...BASE_STATE.drift!, enabled: 1,
            vx_nm_per_s: 3.2, vy_nm_per_s: 0.7, line_jitter_nm: 0.1, max_dt_s: 5,
          },
          specimen: { contamination_enabled: 1, contamination_rate: 250, max_contamination: 0 },
          detectors: {
            haadf: {
              ...BASE_STATE.detectors.haadf,
              dwell_us: 42, dqe: 0.5, readout_e: 2, use_dose_model: 1,
            },
          },
          autofocus: { min_contrast: 0.2 },
        })}
        runActive={false}
      />,
    );
    expect((screen.getByLabelText('Mechanical drift') as HTMLInputElement).checked).toBe(true);
    expect(slider('Drift vx').value).toBe('3.2');
    expect(slider('Drift vy').value).toBe('0.7');
    expect(slider('Line jitter').value).toBe('0.1');
    expect(slider(/Idle-time cap/).value).toBe('5');
    expect((screen.getByLabelText('Contamination') as HTMLInputElement).checked).toBe(true);
    expect(slider(/Rate \(% of nominal/).value).toBe('250');
    expect(slider(/Dwell time/).value).toBe('42');
    expect(slider(/DQE/).value).toBe('0.5');
    expect(slider('Readout noise').value).toBe('2');
    expect((screen.getByLabelText(/Poisson dose model/) as HTMLInputElement).checked).toBe(true);
    expect(slider(/Min contrast for convergence/).value).toBe('0.2');
  });
});
