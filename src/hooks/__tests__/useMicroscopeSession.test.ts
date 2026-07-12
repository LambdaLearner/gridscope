/**
 * The session poller must treat a single failed/stalled poll as "busy"
 * (the twin serves acquisitions serially), flipping to disconnected only
 * after consecutive misses.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useMicroscopeSession } from '../useMicroscopeSession';
import * as twin from '../../api/digitalTwin';

vi.mock('../../api/digitalTwin', async (importOriginal) => {
  const original = await importOriginal<typeof twin>();
  return { ...original, getSession: vi.fn() };
});

const SNAPSHOT = {
  connected: true,
  sample: { name: 'fcc_single_crystal', registered: true },
  run: { active: false, started_at: null, label: null },
  log: [],
};

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe('useMicroscopeSession', () => {
  it('reports the polled session', async () => {
    vi.mocked(twin.getSession).mockResolvedValue(SNAPSHOT as never);
    const { result } = renderHook(() => useMicroscopeSession(1000));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.connected).toBe(true);
    expect(result.current.sampleRegistered).toBe(true);
  });

  it('keeps connected=true after a single poll failure (busy, not down)', async () => {
    vi.mocked(twin.getSession)
      .mockResolvedValueOnce(SNAPSHOT as never)
      .mockRejectedValueOnce(new Error('timeout'))
      .mockResolvedValue(SNAPSHOT as never);
    const { result } = renderHook(() => useMicroscopeSession(1000));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });    // ok
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); }); // 1 failure
    expect(result.current.connected).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); }); // recovers
    expect(result.current.connected).toBe(true);
  });

  it('flips to disconnected after two consecutive failures', async () => {
    vi.mocked(twin.getSession)
      .mockResolvedValueOnce(SNAPSHOT as never)
      .mockRejectedValue(new Error('down'));
    const { result } = renderHook(() => useMicroscopeSession(1000));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(result.current.connected).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(result.current.connected).toBe(false);
  });

  it('a successful poll resets the failure count', async () => {
    vi.mocked(twin.getSession)
      .mockResolvedValueOnce(SNAPSHOT as never)
      .mockRejectedValueOnce(new Error('busy'))
      .mockResolvedValueOnce(SNAPSHOT as never)
      .mockRejectedValueOnce(new Error('busy'))
      .mockResolvedValue(SNAPSHOT as never);
    const { result } = renderHook(() => useMicroscopeSession(1000));
    for (let i = 0; i < 4; i += 1) {
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    }
    expect(result.current.connected).toBe(true);
  });
});
