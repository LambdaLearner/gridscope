/**
 * Microscope Controls window contract tests: the registration gate, the
 * run lock, server-provided limits in the header, and safety-limit
 * rejections rendered distinctly (amber) from generic errors.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MicroscopeControlsPanel } from '../MicroscopeControlsPanel';
import type { SessionSnapshot } from '../../api/digitalTwin';
import * as twin from '../../api/digitalTwin';
import { ApiError } from '../../api/client';

vi.mock('../../api/digitalTwin', async (importOriginal) => {
  const original = await importOriginal<typeof twin>();
  return {
    ...original,
    acquireImage: vi.fn(),
    acquireSpectrum: vi.fn(),
    runAutofocus: vi.fn(),
    setStagePosition: vi.fn(),
    setDetectorSettings: vi.fn(),
    setDiffractionSettings: vi.fn(),
    setMode: vi.fn(),
    setBeamSettings: vi.fn(),
    setResolution: vi.fn(),
  };
});

vi.mock('../../api/simulation', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/simulation')>();
  return {
    ...original,
    getAbtemAvailability: vi.fn().mockResolvedValue({ available: true, detail: null }),
    computeAbtemDiffraction: vi.fn(),
  };
});

const SESSION: SessionSnapshot = {
  connected: true,
  sample: { name: 'fcc_single_crystal', registered: true },
  run: { active: false, started_at: null, label: null },
  log: [],
  state: {
    stage: { x: 0, y: 0, z: 0, a: 0, b: 0 },
    beam: { x: 0, y: 0, current_pA: 50, voltage_kV: 200 },
    vacuum: 1e-6,
    status: 'Idle',
    holder_type: 'DoubleTilt',
    mode: 'IMG',
    detectors: {
      haadf: {
        size: 256, exposure: 0.1, binning: 1, field_of_view_um: 20,
        magnification: 4720, dwell_us: 10, noise_sigma: 12,
      },
    },
    diffraction: { camera_length_mm: 800 },
    environment: 'pristine',
    sample: { name: 'fcc_single_crystal', registered: true },
    stage_limits: { x: 1.5e-3, y: 1.5e-3, z: 1e-3, a: 30, b: 30 },
  },
};

const UNREGISTERED: SessionSnapshot = {
  ...SESSION,
  sample: { name: null, registered: false },
  state: SESSION.state
    ? { ...SESSION.state, sample: { name: null, registered: false } }
    : undefined,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(twin.acquireImage).mockResolvedValue({
    success: true,
    device: 'haadf',
    image: { image_base64: 'abc', width: 256, height: 256, dtype: 'uint16' },
    stage: { x_um: 0, y_um: 0, z_um: 0, a: 0, b: 0 },
    mode: 'IMG',
    sample: { name: 'fcc_single_crystal', registered: true },
    settings: SESSION.state!.detectors.haadf,
  });
  vi.mocked(twin.setStagePosition).mockResolvedValue({
    success: true,
    new_position: { x: 0, y: 0, z: 0, a: 0, b: 0, x_um: 0, y_um: 0, z_um: 0 },
  });
});

describe('MicroscopeControlsPanel', () => {
  it('shows the gate banner and disables controls when no sample is registered', () => {
    render(
      <MicroscopeControlsPanel
        session={UNREGISTERED}
        sampleRegistered={false}
        runActive={false}
      />,
    );
    expect(screen.getByText(/Register a sample in Sample Settings/)).toBeTruthy();
    const acquire = screen.getByRole('button', { name: /^Acquire$/i });
    expect((acquire as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the run-lock banner and disables controls during a script run', () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={true} />,
    );
    expect(screen.getByText(/read-only until it finishes/)).toBeTruthy();
    const acquire = screen.getByRole('button', { name: /^Acquire$/i });
    expect((acquire as HTMLButtonElement).disabled).toBe(true);
  });

  it('displays the server-provided stage limits in the header', () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    expect(screen.getByText(/±1\.5mm xy · ±1\.0mm z · ±30°/)).toBeTruthy();
  });

  it('renders safety-limit rejections with the twin message (amber path)', async () => {
    const detail =
      'Stage move rejected by safety limits: x=+2.000 mm exceeds +/-1.500 mm. Stage did not move.';
    vi.mocked(twin.setStagePosition).mockRejectedValue(new ApiError(400, detail));

    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const moveButtons = screen.getAllByRole('button');
    // First arrow button in the stage pad (ArrowUp)
    const up = moveButtons.find((b) => b.querySelector('.lucide-arrow-up'));
    expect(up).toBeTruthy();
    fireEvent.click(up!);

    await waitFor(() => {
      expect(screen.getByText(detail)).toBeTruthy();
    });
    // Not the generic red error, and no acquisition happened after rejection.
    expect(twin.acquireImage).not.toHaveBeenCalled();
  });

  it('reports autofocus non-convergence without moving on', async () => {
    vi.mocked(twin.runAutofocus).mockResolvedValue({
      success: true,
      result: {
        converged: false,
        reason: 'low contrast',
        best_z_m: 0,
        best_z_um_relative: 0,
        curve_contrast: 0.01,
        n_candidate_peaks: 1,
        scores: [],
      },
      new_z_um: 0,
    });
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Autofocus/i }));
    await waitFor(() => {
      expect(screen.getByText(/did not converge — low contrast/)).toBeTruthy();
    });
    expect(twin.acquireImage).not.toHaveBeenCalled();
  });

  it('allows fields of view down to 100 nm', () => {
    const { container } = render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const sliders = container.querySelectorAll('input[type="range"]');
    const fovSlider = Array.from(sliders).find(
      (s) => (s as HTMLInputElement).min === '0.1',
    ) as HTMLInputElement | undefined;
    expect(fovSlider).toBeTruthy();
    expect(fovSlider!.min).toBe('0.1'); // 100 nm
    expect(fovSlider!.step).toBe('0.1');
    expect(fovSlider!.max).toBe('50');
  });

  it('acquires and displays a frame', async () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Acquire$/i }));
    await waitFor(() => {
      expect(twin.acquireImage).toHaveBeenCalledWith('haadf');
      expect(screen.getByAltText('Microscope view')).toBeTruthy();
    });
  });
});

describe('MicroscopeControlsPanel — v6+ features', () => {
  const DIFF_SESSION: SessionSnapshot = {
    ...SESSION,
    state: { ...SESSION.state!, mode: 'DIFF' },
  };

  it('offers all three modes including EELS', () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    expect(screen.getByRole('button', { name: /Imaging/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Diffraction/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /EELS/i })).toBeTruthy();
  });

  it('renders the discrete resolution windows from the session state', () => {
    const withRes: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        resolution: { resolution_px: 512, allowed: [512, 1024, 2048] },
      },
    };
    render(
      <MicroscopeControlsPanel session={withRes} sampleRegistered={true} runActive={false} />,
    );
    expect(screen.getByRole('button', { name: /^512$/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /1024/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /2048/ })).toBeTruthy();
  });

  it('changes resolution through the control API', async () => {
    vi.mocked(twin.setResolution).mockResolvedValue({
      success: true, resolution_px: 1024, allowed: [512, 1024, 2048],
    });
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /1024/ }));
    await waitFor(() => expect(twin.setResolution).toHaveBeenCalledWith(1024));
  });

  it('shows the kinematical⇄abTEM engine toggle in DIFF mode', async () => {
    render(
      <MicroscopeControlsPanel session={DIFF_SESSION} sampleRegistered={true} runActive={false} />,
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Kinematical/i })).toBeTruthy();
      expect(screen.getByRole('button', { name: /abTEM/i })).toBeTruthy();
    });
  });

  it('greys the abTEM toggle when the backend reports it unavailable', async () => {
    const sim = await import('../../api/simulation');
    vi.mocked(sim.getAbtemAvailability).mockResolvedValue({
      available: false,
      detail: 'The dynamical-diffraction engine requires `abtem` and `ase`.',
    });
    render(
      <MicroscopeControlsPanel session={DIFF_SESSION} sampleRegistered={true} runActive={false} />,
    );
    await waitFor(() => {
      const toggle = screen.getByRole('button', { name: /abTEM/i }) as HTMLButtonElement;
      expect(toggle.disabled).toBe(true);
      expect(toggle.title).toMatch(/not installed/i);
    });
  });

  it('computes a dynamical pattern via the explicit button (never auto)', async () => {
    const sim = await import('../../api/simulation');
    vi.mocked(sim.getAbtemAvailability).mockResolvedValue({ available: true, detail: null });
    vi.mocked(sim.computeAbtemDiffraction).mockResolvedValue({
      success: true,
      engine: 'abtem',
      image: { image_base64: 'aW1n', width: 256, height: 256, dtype: 'uint16' },
      state: {
        sample: 'fcc_single_crystal', params: {}, tilt_a_deg: 0, tilt_b_deg: 0,
        energy_kev: 200, num_frozen_phonons: 0,
      },
      fingerprint: 'abc123', n_atoms: 5000, compute_seconds: 3.2, cached: false,
    });
    render(
      <MicroscopeControlsPanel session={DIFF_SESSION} sampleRegistered={true} runActive={false} />,
    );
    await waitFor(() => screen.getByRole('button', { name: /abTEM/i }));
    fireEvent.click(screen.getByRole('button', { name: /abTEM/i }));
    fireEvent.click(screen.getByRole('button', { name: /Compute dynamical pattern/i }));
    await waitFor(() => {
      expect(sim.computeAbtemDiffraction).toHaveBeenCalledWith({ num_frozen_phonons: 0 });
      expect(screen.getByText(/abTEM · 5,000 atoms/)).toBeTruthy();
    });
  });

  it('acquires an EELS spectrum in EELS mode and plots it', async () => {
    const eelsSession: SessionSnapshot = {
      ...SESSION,
      state: { ...SESSION.state!, mode: 'EELS' },
    };
    vi.mocked(twin.acquireSpectrum).mockResolvedValue({
      success: true,
      energy_ev: [0, 500, 1000],
      intensity: [1, 0.2, 0.05],
      edges: [{ label: 'Fe-L', onset_ev: 708, Z: 26 }],
      zlp_ev: 0, plasmon_ev: 17.6, thickness_nm: 100, elements_Z: [26],
    });
    render(
      <MicroscopeControlsPanel session={eelsSession} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Acquire$/i }));
    await waitFor(() => {
      expect(twin.acquireSpectrum).toHaveBeenCalledWith({
        ev_min: 0, ev_max: 1000, n_channels: 1024,
      });
      expect(screen.getByTestId('spectrum-plot')).toBeTruthy();
      expect(screen.getByTestId('edge-Fe-L')).toBeTruthy();
    });
    expect(twin.acquireImage).not.toHaveBeenCalled();
  });
});

describe('MicroscopeControlsPanel — v2 addenda (z, Live, TIFF, dose meter)', () => {
  it('displays the live z read-out and nudges focus via relative z moves', async () => {
    const withZ: SessionSnapshot = {
      ...SESSION,
      state: { ...SESSION.state!, stage: { ...SESSION.state!.stage, z: 1.75e-6 } },
    };
    render(
      <MicroscopeControlsPanel session={withZ} sampleRegistered={true} runActive={false} />,
    );
    expect(screen.getByTestId('z-readout').textContent).toMatch(/\+1\.75 µm/);
    fireEvent.click(screen.getByTitle('Fine focus +0.25 µm'));
    await waitFor(() => {
      expect(twin.setStagePosition).toHaveBeenCalledWith({ z: 0.25e-6 }, true);
    });
  });

  it('Save TIFF is disabled until a frame exists, then links the capture download', async () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const save = screen.getByRole('button', { name: /TIFF/i }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /^Acquire$/i }));
    await waitFor(() => expect(twin.acquireImage).toHaveBeenCalled());
    expect((screen.getByRole('button', { name: /TIFF/i }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it('Live toggle starts continuous acquisition and disables single Acquire', async () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Live$/i }));
    await waitFor(() => expect(twin.acquireImage).toHaveBeenCalled());
    expect(screen.getByText('LIVE')).toBeTruthy();
    expect((screen.getByRole('button', { name: /^Acquire$/i }) as HTMLButtonElement).disabled)
      .toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Stop live/i }));
    await waitFor(() => {
      expect(screen.queryByText('LIVE')).toBeNull();
    });
  });

  it('Live stops itself when an acquire fails', async () => {
    vi.mocked(twin.acquireImage).mockRejectedValue(new ApiError(503, 'twin down'));
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Live$/i }));
    await waitFor(() => {
      expect(screen.queryByText('LIVE')).toBeNull();
    });
  });

  it('shows the dose meter when damage is enabled, with accumulated vs critical dose', () => {
    const withDose: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        specimen: {
          beam_damage_enabled: 1, contamination_enabled: 0,
          damage_dose_threshold: 3e4, max_accumulated_dose: 1.5e4,
          max_contamination: 0,
        },
      },
    };
    render(
      <MicroscopeControlsPanel session={withDose} sampleRegistered={true} runActive={false} />,
    );
    const meter = screen.getByTestId('dose-meter');
    expect(meter.textContent).toMatch(/1\.5e\+4/);
    expect(meter.textContent).toMatch(/critical 3\.0e\+4/);
  });

  it('hides the dose meter when neither damage nor contamination is on', () => {
    const noDose: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        specimen: {
          beam_damage_enabled: 0, contamination_enabled: 0,
          damage_dose_threshold: 3e4, max_accumulated_dose: 0, max_contamination: 0,
        },
      },
    };
    render(
      <MicroscopeControlsPanel session={noDose} sampleRegistered={true} runActive={false} />,
    );
    expect(screen.queryByTestId('dose-meter')).toBeNull();
  });

  it('offers the standard voltages as a dropdown', () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const select = screen.getByLabelText('Accelerating voltage') as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(['60', '80', '120', '200', '300']);
  });
});
