/**
 * Tests for the script-run SSE client.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { runScript, type RunEvent } from '../execute';
import { ApiError } from '../client';

const mockFetch = vi.fn();
global.fetch = mockFetch as unknown as typeof fetch;

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
  return { ok: true, status: 200, body: stream } as unknown as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe('runScript', () => {
  it('parses streamed events in order', async () => {
    mockFetch.mockResolvedValue(
      sseResponse([
        'data: {"type": "log", "message": "starting"}\n\n',
        'data: {"type": "image", "image": {"image_base64": "abc", "width": 8, "height": 8, "dtype": "uint16"}, "meta": {"label": "t0"}}\n\n',
        'data: {"type": "done", "exit_code": 0, "elapsed_s": 1.2, "images": 1}\n\n',
      ]),
    );
    const events: RunEvent[] = [];
    await runScript('print(1)', (e) => events.push(e));
    expect(events.map((e) => e.type)).toEqual(['log', 'image', 'done']);
    expect(events[0]).toMatchObject({ message: 'starting' });
    expect(events[2]).toMatchObject({ exit_code: 0, images: 1 });
  });

  it('handles frames split across chunks', async () => {
    const frame = 'data: {"type": "log", "message": "split across chunks"}\n\n';
    mockFetch.mockResolvedValue(sseResponse([frame.slice(0, 20), frame.slice(20)]));
    const events: RunEvent[] = [];
    await runScript('x', (e) => events.push(e));
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ message: 'split across chunks' });
  });

  it('throws ApiError with detail when a run is already active (409)', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'A script run is already in progress.' }),
    } as unknown as Response);
    try {
      await runScript('x', () => {});
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(409);
      expect((e as ApiError).message).toContain('already in progress');
    }
  });

  it('emits an error event for a malformed frame instead of crashing', async () => {
    mockFetch.mockResolvedValue(
      sseResponse(['data: this is not json\n\n', 'data: {"type": "done", "exit_code": 0, "elapsed_s": 0, "images": 0}\n\n']),
    );
    const events: RunEvent[] = [];
    await runScript('x', (e) => events.push(e));
    expect(events[0].type).toBe('error');
    expect(events[1].type).toBe('done');
  });
});
