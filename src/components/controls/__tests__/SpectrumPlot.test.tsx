import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SpectrumPlot } from '../SpectrumPlot';
import type { SpectrumResult } from '../../../api/digitalTwin';

const SPECTRUM: SpectrumResult = {
  success: true,
  energy_ev: Array.from({ length: 64 }, (_, i) => i * (1000 / 63)),
  intensity: Array.from({ length: 64 }, (_, i) => Math.exp(-i / 10) + 0.01),
  edges: [{ label: 'Fe-L', onset_ev: 708, Z: 26 }],
  zlp_ev: 0,
  plasmon_ev: 17.6,
  thickness_nm: 100,
  elements_Z: [26],
};

describe('SpectrumPlot', () => {
  it('renders the spectrum with labeled core-loss edge markers', () => {
    render(<SpectrumPlot spectrum={SPECTRUM} />);
    expect(screen.getByTestId('spectrum-plot')).toBeTruthy();
    expect(screen.getByTestId('edge-Fe-L')).toBeTruthy();
    expect(screen.getByText('Fe-L')).toBeTruthy();
    expect(screen.getByText(/energy loss \(eV\)/)).toBeTruthy();
  });

  it('renders nothing for an empty spectrum', () => {
    const { container } = render(
      <SpectrumPlot spectrum={{ ...SPECTRUM, energy_ev: [], intensity: [] }} />,
    );
    expect(container.querySelector('svg')).toBeNull();
  });
});
