/**
 * Shared fetch wrapper for the GridScope backend.
 *
 * Every error response is parsed for its `detail` payload so server messages
 * (e.g. stage safety-limit rejections) reach the user verbatim instead of
 * being flattened into "request failed".
 */

export const API_BASE_URL = 'http://localhost:8000/api';

export class ApiError extends Error {
  /** HTTP status; 0 means the backend itself was unreachable. */
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }

  /** Stage move rejected by the twin's soft limits (HTTP 400 from /stage). */
  get isSafetyLimitRejection(): boolean {
    return this.status === 400 && this.message.includes('safety limits');
  }

  /** Twin/backend not reachable. */
  get isUnavailable(): boolean {
    return this.status === 503 || this.status === 0;
  }

  /** Another operation owns the instrument (script run / no sample). */
  get isConflict(): boolean {
    return this.status === 409;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (e) {
    throw new ApiError(0, `Backend unreachable: ${e instanceof Error ? e.message : e}`);
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
