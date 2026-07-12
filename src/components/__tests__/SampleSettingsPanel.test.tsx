/**
 * Sample Settings window contract tests: registry-driven rendering,
 * the registration gate messaging, and run-lock disabling.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SampleSettingsPanel } from '../SampleSettingsPanel';
import type { SessionSnapshot } from '../../api/digitalTwin';
import * as simulation from '../../api/simulation';

vi.mock('../../api/simulation', () => ({
  listSamples: vi.fn(),
  registerSample: vi.fn(),
  setEnvironment: vi.fn(),
  resetSpecimen: vi.fn(),
  setThickness: vi.fn(),
  setDrift: vi.fn(),
  setSpecimen: vi.fn(),
}));

vi.mock('../../api/digitalTwin', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/digitalTwin')>();
  return { ...original, setDetectorSettings: vi.fn() };
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

function sessionWith(sample: { name: string | null; registered: boolean }): SessionSnapshot {
  return {
    connected: true,
    sample,
    run: { active: false, started_at: null, label: null },
    state: undefined,
    log: [],
  };
}

beforeEach(() => {
  vi.mocked(simulation.listSamples).mockResolvedValue(REGISTRY);
  vi.mocked(simulation.registerSample).mockResolvedValue({
    success: true,
    registered: 'fcc_single_crystal',
    shape: [16, 96, 96],
    params: {},
    thickness: { total_nm: 100, working_nm: 100, z_start_nm: 0, seed: 0 },
    environment: 'pristine',
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

  it('registers the selected sample with the chosen environment', async () => {
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
          environment: 'pristine',
          thickness_nm: 100,
          thickness_seed: 0,
        }),
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
