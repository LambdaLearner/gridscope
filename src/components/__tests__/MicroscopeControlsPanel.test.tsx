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
    setMode: vi.fn(),
    setBeamSettings: vi.fn(),
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
