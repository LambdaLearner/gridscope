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
    runAutofocus: vi.fn(),
    setStagePosition: vi.fn(),
    setDetectorSettings: vi.fn(),
    setDiffractionSettings: vi.fn(),
    setMode: vi.fn(),
    setBeamSettings: vi.fn(),
    setResolution: vi.fn(),
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

  it('allows fields of view down to 1 nm (atomistic samples)', () => {
    const { container } = render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const sliders = container.querySelectorAll('input[type="range"]');
    const fovSlider = Array.from(sliders).find(
      (s) => (s as HTMLInputElement).min === '0.001',
    ) as HTMLInputElement | undefined;
    expect(fovSlider).toBeTruthy();
    expect(fovSlider!.min).toBe('0.001'); // 1 nm
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
  it('offers exactly two modes labelled STEM / SAED', () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const stem = screen.getByRole('button', { name: /STEM/ });
    expect(stem).toBeTruthy();
    expect(screen.getByRole('button', { name: /SAED/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /EELS/i })).toBeNull();
    // the mode toggle holds exactly the two buttons
    expect(stem.parentElement!.querySelectorAll('button')).toHaveLength(2);
    // viewer badge names the technique explicitly
    expect(screen.getByText('STEM imaging')).toBeTruthy();
  });

  it('renders the discrete resolution windows from the session state', () => {
    const withRes: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        resolution: { resolution_px: 1024, allowed: [1024, 2048, 4096] },
      },
    };
    render(
      <MicroscopeControlsPanel session={withRes} sampleRegistered={true} runActive={false} />,
    );
    expect(screen.getByRole('button', { name: /^1024$/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^2048$/ })).toBeTruthy();
    // 4096 is labelled as the offline-capture window
    expect(screen.getByRole('button', { name: /4096·offline/ })).toBeTruthy();
  });

  it('changes resolution through the control API', async () => {
    vi.mocked(twin.setResolution).mockResolvedValue({
      success: true, resolution_px: 2048, allowed: [1024, 2048, 4096],
    });
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^2048$/ }));
    await waitFor(() => expect(twin.setResolution).toHaveBeenCalledWith(2048));
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
    // default step is 1 µm; the ± buttons apply the selected step
    fireEvent.click(screen.getByTitle('Focus +1 µm'));
    await waitFor(() => {
      expect(twin.setStagePosition).toHaveBeenCalledWith({ z: 1e-6 }, true);
    });
    // switching the step changes the applied nudge
    fireEvent.change(screen.getByLabelText('Focus step'), { target: { value: '0.1' } });
    fireEvent.click(screen.getByTitle('Focus −0.1 µm'));
    await waitFor(() => {
      expect(twin.setStagePosition).toHaveBeenCalledWith({ z: -0.1e-6 }, true);
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

  it('shows the contamination meter when contamination is on, with accumulated exposure', () => {
    const withContam: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        specimen: {
          contamination_enabled: 1, contamination_rate: 100,
          max_contamination: 7.7,
        },
      },
    };
    render(
      <MicroscopeControlsPanel session={withContam} sampleRegistered={true} runActive={false} />,
    );
    const meter = screen.getByTestId('dose-meter');
    expect(meter.textContent).toMatch(/7\.7e\+0/);
    // 1 - exp(-7.7/7.7) = 63% saturated at exactly one CONTAM_DOSE_SCALE
    expect(meter.textContent).toMatch(/63% saturated/);
  });

  it('hides the contamination meter when contamination is off', () => {
    const noContam: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        specimen: {
          contamination_enabled: 0, contamination_rate: 100,
          max_contamination: 0,
        },
      },
    };
    render(
      <MicroscopeControlsPanel session={noContam} sampleRegistered={true} runActive={false} />,
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

describe('MicroscopeControlsPanel — v3 integration (steps, units, 4096 policy)', () => {
  it('offers the fine tilt steps 0.1/0.5/1/2°', () => {
    const { container } = render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const tiltSelect = Array.from(container.querySelectorAll('select')).find((sel) =>
      Array.from(sel.options).some((o) => o.textContent === '0.1°'),
    )!;
    expect(Array.from(tiltSelect.options).map((o) => o.textContent)).toEqual([
      '0.1°', '0.5°', '1°', '2°',
    ]);
  });

  it('offers focus steps 0.1/0.5/1/5/10/25 µm', () => {
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const focusSelect = screen.getByLabelText('Focus step') as HTMLSelectElement;
    expect(Array.from(focusSelect.options).map((o) => o.textContent)).toEqual([
      '0.1 µm', '0.5 µm', '1 µm', '5 µm', '10 µm', '25 µm',
    ]);
  });

  it('tilts by the selected fine step', async () => {
    const { container } = render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    const tiltSelect = Array.from(container.querySelectorAll('select')).find((sel) =>
      Array.from(sel.options).some((o) => o.textContent === '0.1°'),
    )!;
    fireEvent.change(tiltSelect, { target: { value: '0.5' } });
    fireEvent.click(screen.getByTitle('Tilt α +0.5°'));
    await waitFor(() => {
      expect(twin.setStagePosition).toHaveBeenCalledWith({ a: 0.5, b: 0 }, false);
    });
  });

  it('shows position to 1 nm and FOV in nm in the viewer overlay', async () => {
    vi.mocked(twin.acquireImage).mockResolvedValue({
      success: true,
      device: 'haadf',
      image: { image_base64: 'abc', width: 1024, height: 1024, dtype: 'uint16' },
      stage: { x_um: 1.2345, y_um: -0.0011, z_um: 0, a: 0, b: 0 },
      mode: 'IMG',
      sample: { name: 'fcc_single_crystal', registered: true },
      settings: { ...SESSION.state!.detectors.haadf, field_of_view_um: 0.5 },
    });
    render(
      <MicroscopeControlsPanel session={SESSION} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Acquire$/i }));
    await waitFor(() => {
      const overlay = screen.getByTestId('position-overlay').textContent!;
      expect(overlay).toContain('(1.234, -0.001) µm'); // 1 nm precision
      expect(overlay).toContain('FOV: 500 nm');        // nm, not µm
    });
  });

  it('disables Live at 4096 (offline-capture window)', () => {
    const at4096: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        resolution: { resolution_px: 4096, allowed: [1024, 2048, 4096] },
      },
    };
    render(
      <MicroscopeControlsPanel session={at4096} sampleRegistered={true} runActive={false} />,
    );
    const liveBtn = screen.getByRole('button', { name: /^Live$/i }) as HTMLButtonElement;
    expect(liveBtn.disabled).toBe(true);
    expect(liveBtn.title).toMatch(/offline capture/i);
  });

  it('asks for confirmation before a tilted 4096 acquire', async () => {
    const tilted4096: SessionSnapshot = {
      ...SESSION,
      state: {
        ...SESSION.state!,
        stage: { ...SESSION.state!.stage, a: 5, b: 10 },
        resolution: { resolution_px: 4096, allowed: [1024, 2048, 4096] },
      },
    };
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(
      <MicroscopeControlsPanel session={tilted4096} sampleRegistered={true} runActive={false} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /^Acquire$/i }));
    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(twin.acquireImage).not.toHaveBeenCalled(); // declined -> no acquire
    confirmSpy.mockRestore();
  });
});
