/**
 * SeedField is the reproducibility UX: after randomizing, the resulting
 * number must be visible so it can be written down and re-entered.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SeedField } from '../SeedField';

describe('SeedField', () => {
  it('shows the current seed value', () => {
    render(<SeedField label="Structure seed" value={12345} onChange={vi.fn()} />);
    const input = screen.getByLabelText('Structure seed') as HTMLInputElement;
    expect(input.value).toBe('12345');
  });

  it('randomize produces an int in [0, 2^31-1] and reports it', () => {
    const onChange = vi.fn();
    render(<SeedField label="Thickness seed" value={0} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /Randomize Thickness seed/i }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const seed = onChange.mock.calls[0][0];
    expect(Number.isInteger(seed)).toBe(true);
    expect(seed).toBeGreaterThanOrEqual(0);
    expect(seed).toBeLessThanOrEqual(2 ** 31 - 1);
  });

  it('the randomized value stays visible in the field (controlled)', () => {
    let value = 0;
    const onChange = vi.fn((v: number) => { value = v; });
    const { rerender } = render(
      <SeedField label="Structure seed" value={value} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Randomize Structure seed/i }));
    rerender(<SeedField label="Structure seed" value={value} onChange={onChange} />);
    const input = screen.getByLabelText('Structure seed') as HTMLInputElement;
    expect(input.value).toBe(String(value));
  });

  it('clamps manual input to the valid seed range', () => {
    const onChange = vi.fn();
    render(<SeedField label="Structure seed" value={0} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Structure seed'), {
      target: { value: String(2 ** 31 + 5) },
    });
    expect(onChange).toHaveBeenCalledWith(2 ** 31 - 1);
    fireEvent.change(screen.getByLabelText('Structure seed'), {
      target: { value: '-3' },
    });
    expect(onChange).toHaveBeenCalledWith(0);
  });
});
