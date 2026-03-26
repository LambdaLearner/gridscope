import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  executeOperations,
  executeSimple,
  acquireImage,
  moveStage,
  runAutofocus,
  tiltStage,
  scanGrid,
} from '../execute';

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

// --------------- executeOperations ---------------

describe('executeOperations', () => {
  it('sends operations to /run and returns results', async () => {
    const expected = { results: [{ operation: 'acquire', success: true }] };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(expected),
    });

    const ops = [{ operation: 'acquire' }];
    const result = await executeOperations(ops);

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/execute/run');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ operations: ops });
    expect(result).toEqual(expected);
  });

  it('throws on non-ok response with detail', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({ detail: 'Server error' }),
    });

    await expect(executeOperations([])).rejects.toThrow('Server error');
  });

  it('throws generic message when response body is not JSON', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.reject(new Error('not json')),
    });

    await expect(executeOperations([])).rejects.toThrow('Unknown error');
  });
});

// --------------- executeSimple ---------------

describe('executeSimple', () => {
  it('sends action + params to /simple', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await executeSimple('acquire', { fov_um: 10 });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({ action: 'acquire', params: { fov_um: 10 } });
  });

  it('defaults params to empty object', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await executeSimple('autofocus');

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({ action: 'autofocus', params: {} });
  });
});

// --------------- acquireImage ---------------

describe('acquireImage', () => {
  it('calls executeSimple with acquire and no fov when omitted', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true, action: 'acquire' }),
    });

    await acquireImage();

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.action).toBe('acquire');
    expect(body.params).toEqual({});
  });

  it('passes fov_um when provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true, action: 'acquire' }),
    });

    await acquireImage(15);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.params).toEqual({ fov_um: 15 });
  });
});

// --------------- moveStage ---------------

describe('moveStage', () => {
  it('sends move with x, y, relative params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true, action: 'move', stage: { x_um: 10, y_um: 20, z_um: 0 } }),
    });

    await moveStage(10, 20, false);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({ action: 'move', params: { x_um: 10, y_um: 20, relative: false } });
  });

  it('defaults relative to true', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await moveStage(5, 5);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.params.relative).toBe(true);
  });
});

// --------------- runAutofocus ---------------

describe('runAutofocus', () => {
  it('sends autofocus with default params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true, action: 'autofocus' }),
    });

    await runAutofocus();

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({ action: 'autofocus', params: { z_range_um: 4.0, z_steps: 9 } });
  });

  it('sends custom z_range and z_steps', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await runAutofocus(2.0, 5);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.params).toEqual({ z_range_um: 2.0, z_steps: 5 });
  });
});

// --------------- tiltStage ---------------

describe('tiltStage', () => {
  it('sends tilt with a and b angles', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true, action: 'tilt' }),
    });

    await tiltStage(15, -10, false);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({ action: 'tilt', params: { a: 15, b: -10, relative: false } });
  });

  it('omits a/b when undefined', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await tiltStage(undefined, 5, true);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.params).toEqual({ b: 5, relative: true });
    expect(body.params.a).toBeUndefined();
  });

  it('defaults relative to false', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    });

    await tiltStage(0, 0);

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.params.relative).toBe(false);
  });
});

// --------------- scanGrid ---------------

describe('scanGrid', () => {
  it('sends scan_grid with all params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ success: true, action: 'scan_grid', images: [], total_tiles: 9 }),
    });

    await scanGrid({ rows: 3, cols: 3, step_um: 5, autofocus: true });

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body).toEqual({
      action: 'scan_grid',
      params: { rows: 3, cols: 3, step_um: 5, autofocus: true },
    });
  });
});
