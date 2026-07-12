/**
 * ParamField renders sample parameters purely from param_schema
 * (spec §1.2: do not hard-code parameter controls).
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ParamField } from '../ParamField';

describe('ParamField', () => {
  it('renders an int spinbox with the schema bounds and clamps input', () => {
    const onChange = vi.fn();
    render(
      <ParamField
        name="n_dislocations"
        schema={{ type: 'int', min: 1, max: 40 }}
        value={12}
        onChange={onChange}
      />,
    );
    const input = screen.getByLabelText('n_dislocations') as HTMLInputElement;
    expect(input.min).toBe('1');
    expect(input.max).toBe('40');
    fireEvent.change(input, { target: { value: '99' } });
    expect(onChange).toHaveBeenCalledWith(40);
    fireEvent.change(input, { target: { value: '7' } });
    expect(onChange).toHaveBeenCalledWith(7);
  });

  it('renders a float spinbox with ~1/100 step', () => {
    render(
      <ParamField
        name="burgers_A"
        schema={{ type: 'float', min: 0.5, max: 10 }}
        value={2.86}
        onChange={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('burgers_A') as HTMLInputElement;
    expect(Number(input.step)).toBeCloseTo(0.095, 3);
  });

  it('renders a checkbox for bool params', () => {
    const onChange = vi.fn();
    render(
      <ParamField name="auto_fit" schema={{ type: 'bool' }} value={true} onChange={onChange} />,
    );
    const box = screen.getByLabelText('auto_fit') as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it('renders a text field for str params', () => {
    const onChange = vi.fn();
    render(
      <ParamField
        name="file_path"
        schema={{ type: 'str' }}
        value="sample_data/poly.xyz"
        onChange={onChange}
      />,
    );
    const input = screen.getByLabelText('file_path') as HTMLInputElement;
    expect(input.value).toBe('sample_data/poly.xyz');
    fireEvent.change(input, { target: { value: 'other.cif' } });
    expect(onChange).toHaveBeenCalledWith('other.cif');
  });
});
