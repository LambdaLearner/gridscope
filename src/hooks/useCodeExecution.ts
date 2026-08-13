/**
 * useCodeExecution — runs generated scripts server-side and streams results.
 *
 * The script executes in a sandboxed subprocess on the backend (the exact
 * code you would deploy on a real instrument). Log lines, acquired frames,
 * and errors stream back over SSE and land in the execution log.
 */

import { useCallback, useRef, useState } from 'react';
import { runScript } from '../api/execute';
import { ApiError } from '../api/client';
import type { AcquiredImage, ExecutionLog } from '../types/execution';

export interface UseCodeExecutionReturn {
  executionLogs: ExecutionLog[];
  acquiredImages: AcquiredImage[];
  isExecuting: boolean;
  handleRunCode: (code: string) => Promise<void>;
  handleStopExecution: () => void;
  clearResults: () => void;
}

export function useCodeExecution(): UseCodeExecutionReturn {
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [acquiredImages, setAcquiredImages] = useState<AcquiredImage[]>([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const addLog = useCallback(
    (type: ExecutionLog['type'], message: string, data?: ExecutionLog['data']) => {
      setExecutionLogs((prev) => [
        ...prev,
        {
          id: Date.now().toString() + Math.random().toString(36).slice(2, 6),
          type,
          message,
          timestamp: new Date(),
          data,
        },
      ]);
    },
    [],
  );

  const clearResults = useCallback(() => {
    setExecutionLogs([]);
    setAcquiredImages([]);
  }, []);

  const handleStopExecution = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleRunCode = useCallback(
    async (code: string) => {
      setIsExecuting(true);
      setExecutionLogs([]);
      setAcquiredImages([]);
      addLog('info', 'Starting script on the digital twin (sandboxed run)...');

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        await runScript(
          code,
          (event) => {
            switch (event.type) {
              case 'log':
                addLog('command', event.message);
                break;
              case 'error':
                addLog('error', event.message);
                break;
              case 'image': {
                const meta = event.meta as Record<string, unknown>;
                const src = `data:image/png;base64,${event.image.image_base64}`;
                // The embedded report_image helper reads the stage back from
                // the instrument and attaches x_um/y_um/z_um/a_deg/b_deg to
                // every frame — these are the authoritative acquire-time
                // coordinates (script-supplied meta keys win over readback).
                const stage = {
                  x_um: Number(meta.x_um ?? 0),
                  y_um: Number(meta.y_um ?? 0),
                  z_um: Number(meta.z_um ?? 0),
                  a: meta.a_deg !== undefined ? Number(meta.a_deg) : undefined,
                  b: meta.b_deg !== undefined ? Number(meta.b_deg) : undefined,
                };
                setAcquiredImages((prev) => [
                  ...prev,
                  {
                    image_base64: src,
                    x_um: stage.x_um,
                    y_um: stage.y_um,
                    z_um: stage.z_um,
                    a: stage.a,
                    b: stage.b,
                    label: meta.label !== undefined ? String(meta.label) : undefined,
                  },
                ]);
                addLog('image', `Frame received${meta.label ? ` — ${meta.label}` : ''}`, {
                  image_base64: src,
                  stage,
                });
                break;
              }
              case 'done':
                addLog(
                  event.exit_code === 0 ? 'success' : 'error',
                  `Run finished (exit ${event.exit_code}) — ${event.images} frame(s) in ${event.elapsed_s}s`,
                );
                break;
            }
          },
          { signal: abort.signal },
        );
      } catch (error) {
        if (abort.signal.aborted) {
          addLog('error', 'Run stopped by user (server finishes cleanup in background).');
        } else if (error instanceof ApiError) {
          addLog('error', error.message);
        } else {
          addLog('error', `Execution failed: ${error}`);
        }
      } finally {
        abortRef.current = null;
        setIsExecuting(false);
      }
    },
    [addLog],
  );

  return {
    executionLogs,
    acquiredImages,
    isExecuting,
    handleRunCode,
    handleStopExecution,
    clearResults,
  };
}
