/**
 * Tests for the shared API client — error-detail parsing is what lets
 * safety-limit rejections reach the user verbatim.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiFetch, ApiError } from '../client';

const mockFetch = vi.fn();
global.fetch = mockFetch as unknown as typeof fetch;

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe('apiFetch', () => {
  it('returns parsed JSON on success', async () => {
    mockFetch.mockResolvedValue(jsonResponse(200, { limits: { x: 0.0015 } }));
    const result = await apiFetch<{ limits: { x: number } }>('/microscope/limits');
    expect(result.limits.x).toBe(0.0015);
  });

  it('surfaces the server detail message verbatim on 400', async () => {
    const detail =
      'Stage move rejected by safety limits: x=+2.000 mm exceeds +/-1.500 mm. Stage did not move.';
    mockFetch.mockResolvedValue(jsonResponse(400, { detail }));
    await expect(apiFetch('/microscope/stage')).rejects.toMatchObject({
      status: 400,
      message: detail,
    });
  });

  it('flags safety-limit rejections', async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(400, { detail: 'Stage move rejected by safety limits: z' }),
    );
    try {
      await apiFetch('/microscope/stage');
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).isSafetyLimitRejection).toBe(true);
      expect((e as ApiError).isUnavailable).toBe(false);
    }
  });

  it('marks 503 as unavailable', async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(503, { detail: 'Digital twin server unreachable.' }),
    );
    try {
      await apiFetch('/microscope/state');
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).isUnavailable).toBe(true);
    }
  });

  it('marks 409 as conflict (run lock / no sample)', async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(409, { detail: 'A script run is in progress' }),
    );
    try {
      await apiFetch('/microscope/acquire');
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).isConflict).toBe(true);
    }
  });

  it('handles a non-JSON error body without crashing', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json');
      },
    } as unknown as Response);
    await expect(apiFetch('/x')).rejects.toMatchObject({ status: 502 });
  });

  it('maps network failure to status 0 / unavailable', async () => {
    mockFetch.mockRejectedValue(new TypeError('Failed to fetch'));
    try {
      await apiFetch('/microscope/status');
      expect.unreachable();
    } catch (e) {
      expect((e as ApiError).status).toBe(0);
      expect((e as ApiError).isUnavailable).toBe(true);
    }
  });
});
