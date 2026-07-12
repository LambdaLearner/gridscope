/**
 * API client for server-side script execution (/api/execute).
 *
 * The generated Python runs in a sandboxed subprocess on the backend — the
 * exact script a user would deploy on a real instrument. Events stream back
 * over SSE: logs, acquired frames (via the image-marker protocol), errors,
 * and a final done event.
 */

import { API_BASE_URL, ApiError } from './client';

export interface RunLogEvent { type: 'log'; message: string }
export interface RunErrorEvent { type: 'error'; message: string }
export interface RunImageEvent {
  type: 'image';
  image: { image_base64: string; width: number; height: number; dtype: string };
  meta: Record<string, unknown>;
}
export interface RunDoneEvent {
  type: 'done';
  exit_code: number;
  elapsed_s: number;
  images: number;
}
export type RunEvent = RunLogEvent | RunErrorEvent | RunImageEvent | RunDoneEvent;

export interface RunStatus {
  active: boolean;
  started_at: number | null;
  label: string | null;
}

export async function getRunStatus(): Promise<RunStatus> {
  const response = await fetch(`${API_BASE_URL}/execute/status`);
  if (!response.ok) throw new ApiError(response.status, 'Failed to get run status');
  return response.json();
}

/**
 * Run a script, invoking `onEvent` for each streamed event.
 * Resolves when the stream ends; rejects with ApiError on start failure
 * (409 = a run is already active). Abort via the optional AbortSignal.
 */
export async function runScript(
  code: string,
  onEvent: (event: RunEvent) => void,
  options: { timeoutS?: number; label?: string; signal?: AbortSignal } = {},
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/execute/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code,
      timeout_s: options.timeoutS ?? 300,
      label: options.label ?? null,
    }),
    signal: options.signal,
  });

  if (!response.ok || !response.body) {
    let detail = `Run failed to start (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // keep generic detail
    }
    throw new ApiError(response.status, detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as RunEvent);
        } catch {
          // Malformed frame — surface rather than swallow.
          onEvent({ type: 'error', message: 'Received malformed event from server' });
        }
      }
    }
  }
}
