/**
 * The FOV⇄magnification link is a spec-mandated correctness contract
 * (mag = MAG_K / fov_metres): editing either field updates the other.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LinkedFovMag } from '../LinkedFovMag';
import { fovUmToMag, magToFovUm, MAG_K } from '../../../api/digitalTwin';

describe('MAG_K math', () => {
  it('matches the twin calibration: 57 kx = 1.6564523008 µm', () => {
    expect(magToFovUm(57000)).toBeCloseTo(1.6564523008, 9);
    expect(fovUmToMag(1.6564523008)).toBeCloseTo(57000, 6);
    expect(MAG_K).toBeCloseTo(0.0944177811456, 12);
  });

  it('is self-inverse', () => {
    expect(magToFovUm(fovUmToMag(3.7))).toBeCloseTo(3.7, 9);
  });
});

describe('LinkedFovMag', () => {
  it('shows both views of the current FOV', () => {
    render(<LinkedFovMag fovUm={20} onCommit={vi.fn()} />);
    const fov = screen.getByLabelText('Field of view (µm)') as HTMLInputElement;
    const mag = screen.getByLabelText('Magnification (kx)') as HTMLInputElement;
    expect(Number(fov.value)).toBeCloseTo(20, 2);
    expect(Number(mag.value)).toBeCloseTo(fovUmToMag(20) / 1e3, 1);
  });

  it('editing FOV live-updates the magnification field', () => {
    render(<LinkedFovMag fovUm={20} onCommit={vi.fn()} />);
    const fov = screen.getByLabelText('Field of view (µm)');
    fireEvent.change(fov, { target: { value: '2' } });
    const mag = screen.getByLabelText('Magnification (kx)') as HTMLInputElement;
    expect(Number(mag.value)).toBeCloseTo(fovUmToMag(2) / 1e3, 1);
  });

  it('editing magnification live-updates the FOV field', () => {
    render(<LinkedFovMag fovUm={20} onCommit={vi.fn()} />);
    const mag = screen.getByLabelText('Magnification (kx)');
    fireEvent.change(mag, { target: { value: '57' } });
    const fov = screen.getByLabelText('Field of view (µm)') as HTMLInputElement;
    // Display rounds to 2 decimals for FOV >= 1 µm; the exact value is 1.6564…
    expect(Number(fov.value)).toBeCloseTo(1.66, 2);
  });

  it('commits the FOV equivalent when magnification is committed', () => {
    const onCommit = vi.fn();
    render(<LinkedFovMag fovUm={20} onCommit={onCommit} />);
    const mag = screen.getByLabelText('Magnification (kx)');
    fireEvent.change(mag, { target: { value: '57' } });
    fireEvent.keyDown(mag, { key: 'Enter' });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit.mock.calls[0][0]).toBeCloseTo(1.6564523008, 6);
  });

  it('clamps committed FOV to the allowed range', () => {
    const onCommit = vi.fn();
    render(<LinkedFovMag fovUm={20} onCommit={onCommit} minFovUm={0.005} maxFovUm={100} />);
    const fov = screen.getByLabelText('Field of view (µm)');
    fireEvent.change(fov, { target: { value: '5000' } });
    fireEvent.blur(fov);
    expect(onCommit).toHaveBeenCalledWith(100);
  });
});
