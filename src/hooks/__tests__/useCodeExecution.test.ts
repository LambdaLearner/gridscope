/**
 * useCodeExecution — the streamed-frame position seam (v3 fix for "position
 * shown is not correct while running LLM code").
 *
 * The embedded report_image helper attaches the authoritative stage to each
 * image event's meta; the hook must surface it BOTH on acquiredImages and on
 * the per-log data.stage that ExecutionPanel's inline preview renders (the
 * always-(0.00, 0.00) bug lived in the latter).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useCodeExecution } from '../useCodeExecution';
import * as executeApi from '../../api/execute';
import type { RunEvent } from '../../api/execute';

vi.mock('../../api/execute', () => ({
  runScript: vi.fn(),
}));

const IMAGE_EVENT: RunEvent = {
  type: 'image',
  image: { image_base64: 'abc', width: 8, height: 8, dtype: 'uint16' },
  meta: {
    label: 'tile 3',
    x_um: 12.5, y_um: -3.125, z_um: 0.5, a_deg: 5, b_deg: -2,
    stage: { x_um: 12.5, y_um: -3.125, z_um: 0.5, a_deg: 5, b_deg: -2 },
  },
} as unknown as RunEvent;

beforeEach(() => {
  vi.mocked(executeApi.runScript).mockReset();
});

function mockRun(events: RunEvent[]) {
  vi.mocked(executeApi.runScript).mockImplementation(async (_code, onEvent) => {
    for (const e of events) onEvent(e);
  });
}

describe('useCodeExecution — stage on streamed frames', () => {
  it('surfaces the helper-attached stage on acquiredImages', async () => {
    mockRun([IMAGE_EVENT, { type: 'done', exit_code: 0, elapsed_s: 1, images: 1 } as RunEvent]);
    const { result } = renderHook(() => useCodeExecution());
    await act(() => result.current.handleRunCode('code'));
    await waitFor(() => expect(result.current.acquiredImages).toHaveLength(1));
    const img = result.current.acquiredImages[0];
    expect(img.x_um).toBe(12.5);
    expect(img.y_um).toBe(-3.125);
    expect(img.z_um).toBe(0.5);
    expect(img.a).toBe(5);
    expect(img.b).toBe(-2);
    expect(img.label).toBe('tile 3');
  });

  it('populates data.stage on the image log entry (inline preview readout)', async () => {
    mockRun([IMAGE_EVENT, { type: 'done', exit_code: 0, elapsed_s: 1, images: 1 } as RunEvent]);
    const { result } = renderHook(() => useCodeExecution());
    await act(() => result.current.handleRunCode('code'));
    const imageLog = result.current.executionLogs.find((l) => l.type === 'image')!;
    expect(imageLog.data?.stage).toMatchObject({
      x_um: 12.5, y_um: -3.125, z_um: 0.5, a: 5, b: -2,
    });
  });

  it('defaults to zeros when the script supplied no position meta', async () => {
    mockRun([
      {
        type: 'image',
        image: { image_base64: 'abc', width: 8, height: 8, dtype: 'uint16' },
        meta: { label: 'bare' },
      } as unknown as RunEvent,
      { type: 'done', exit_code: 0, elapsed_s: 1, images: 0 } as RunEvent,
    ]);
    const { result } = renderHook(() => useCodeExecution());
    await act(() => result.current.handleRunCode('code'));
    const img = result.current.acquiredImages[0];
    expect(img.x_um).toBe(0);
    expect(img.a).toBeUndefined(); // tilt shown only when actually known
  });
});
