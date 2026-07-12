/**
 * useMicroscopeSession — the single session poller.
 *
 * One GET /microscope/session request on an interval feeds every panel
 * (connection status, microscope state, registered sample, run status,
 * command log). An in-flight guard skips a tick if the previous request is
 * still pending, so slow twin renders never cause poll pileup.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getSession, type SessionSnapshot } from '../api/digitalTwin';

export interface UseMicroscopeSessionReturn {
  session: SessionSnapshot | null;
  connected: boolean;
  sampleRegistered: boolean;
  runActive: boolean;
  refresh: () => Promise<void>;
}

export function useMicroscopeSession(intervalMs = 2000): UseMicroscopeSessionReturn {
  const [session, setSession] = useState<SessionSnapshot | null>(null);
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const snapshot = await getSession();
      setSession(snapshot);
    } catch {
      setSession((prev) => (prev ? { ...prev, connected: false } : null));
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, intervalMs);
    return () => clearInterval(interval);
  }, [refresh, intervalMs]);

  return {
    session,
    connected: session?.connected ?? false,
    sampleRegistered: session?.sample?.registered ?? false,
    runActive: session?.run?.active ?? false,
    refresh,
  };
}
