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

describe('ParamField — choices dropdowns (v3 schema)', () => {
  const ZONE_SCHEMA = {
    type: 'str' as const,
    choices: ['001', '011', '110', '111', '112'],
  };

  it('renders a str param with choices as a dropdown, not a text field', () => {
    render(
      <ParamField
        name="zone_axis"
        schema={ZONE_SCHEMA}
        value="111"
        onChange={vi.fn()}
      />,
    );
    const select = screen.getByLabelText('zone_axis') as HTMLSelectElement;
    expect(select.tagName).toBe('SELECT');
    expect(Array.from(select.options).map((o) => o.value)).toEqual(ZONE_SCHEMA.choices);
    expect(select.value).toBe('111');
  });

  it('commits the selected choice', () => {
    const onChange = vi.fn();
    render(
      <ParamField name="zone_axis" schema={ZONE_SCHEMA} value="111" onChange={onChange} />,
    );
    fireEvent.change(screen.getByLabelText('zone_axis'), { target: { value: '011' } });
    expect(onChange).toHaveBeenCalledWith('011');
  });

  it('falls back to the first choice when the value is unset', () => {
    render(
      <ParamField name="zone_axis" schema={ZONE_SCHEMA} value={undefined} onChange={vi.fn()} />,
    );
    expect((screen.getByLabelText('zone_axis') as HTMLSelectElement).value).toBe('001');
  });

  it('still renders a plain text field for str params WITHOUT choices', () => {
    render(
      <ParamField
        name="file_path"
        schema={{ type: 'str' }}
        value="sample_data/polycrystal.xyz"
        onChange={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('file_path') as HTMLInputElement;
    expect(input.tagName).toBe('INPUT');
    expect(input.type).toBe('text');
  });
});
