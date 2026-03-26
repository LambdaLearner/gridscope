import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCodeExecution } from '../useCodeExecution';
import type { ExecutionPlan } from '../../types/execution';

// Mock all API modules
vi.mock('../../api/digitalTwin', () => ({
  getMicroscopeStatus: vi.fn(),
}));
vi.mock('../../api/execute', () => ({
  executeSimple: vi.fn(),
}));

import { getMicroscopeStatus } from '../../api/digitalTwin';
import { executeSimple } from '../../api/execute';

const mockGetStatus = vi.mocked(getMicroscopeStatus);
const mockExecuteSimple = vi.mocked(executeSimple);

// Stub global fetch for set_mode / set_beam / set_sample (raw fetch calls in hook)
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

beforeEach(() => {
  vi.clearAllMocks();
  mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
});

function renderExecutionHook() {
  const setCurrentSampleType = vi.fn();
  const setCurrentMode = vi.fn();
  return {
    ...renderHook(() =>
      useCodeExecution('au_nanoparticles', 'IMG', setCurrentSampleType, setCurrentMode),
    ),
    setCurrentSampleType,
    setCurrentMode,
  };
}

// --------------- initial state ---------------

describe('initial state', () => {
  it('returns empty logs and images, not executing', () => {
    const { result } = renderExecutionHook();
    expect(result.current.executionLogs).toEqual([]);
    expect(result.current.acquiredImages).toEqual([]);
    expect(result.current.isExecuting).toBe(false);
  });
});

// --------------- clearResults ---------------

describe('clearResults', () => {
  it('clears logs and images', async () => {
    // Simulate an execution that adds logs
    mockGetStatus.mockResolvedValue({ connected: false } as any);

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('# empty');
    });

    // Should have at least 1 error log (not connected)
    expect(result.current.executionLogs.length).toBeGreaterThan(0);

    act(() => {
      result.current.clearResults();
    });

    expect(result.current.executionLogs).toEqual([]);
    expect(result.current.acquiredImages).toEqual([]);
  });
});

// --------------- connection check ---------------

describe('connection check', () => {
  it('logs error when not connected', async () => {
    mockGetStatus.mockResolvedValue({ connected: false } as any);

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('acquire_image()');
    });

    const errorLogs = result.current.executionLogs.filter(l => l.type === 'error');
    expect(errorLogs.length).toBe(1);
    expect(errorLogs[0].message).toMatch(/not connected/i);
    expect(result.current.isExecuting).toBe(false);
  });
});

// --------------- plan-based dispatch ---------------

describe('plan-based dispatch', () => {
  const connectedStatus = {
    connected: true,
    state: { sample_type: 'au_nanoparticles', mode: 'IMG', stage: { a: 0, b: 0 } },
  };

  beforeEach(() => {
    mockGetStatus.mockResolvedValue(connectedStatus as any);
  });

  it('dispatches acquire step', async () => {
    mockExecuteSimple.mockResolvedValue({
      image: { image_base64: 'data:img' },
      stage: { x_um: 0, y_um: 0, z_um: 0 },
    } as any);

    const plan: ExecutionPlan = {
      plan_type: 'single_acquire',
      summary: 'Acquire one image',
      steps: [{ action: 'acquire', params: {}, description: 'Acquire image' }],
    };

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('', plan);
    });

    // Should have called executeSimple with 'acquire'
    expect(mockExecuteSimple).toHaveBeenCalledWith('acquire', {});
    // Should have acquired an image
    expect(result.current.acquiredImages.length).toBe(1);
    expect(result.current.acquiredImages[0].image_base64).toBe('data:img');
  });

  it('dispatches move step', async () => {
    mockExecuteSimple.mockResolvedValue({
      new_position: { x_um: 10, y_um: 20, z_um: 0 },
    } as any);

    const plan: ExecutionPlan = {
      plan_type: 'move',
      summary: 'Move stage',
      steps: [{ action: 'move', params: { x_um: 10, y_um: 20 }, description: 'Move stage' }],
    };

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('', plan);
    });

    expect(mockExecuteSimple).toHaveBeenCalledWith('move', { x_um: 10, y_um: 20 });
    const successLogs = result.current.executionLogs.filter(l => l.type === 'success');
    expect(successLogs.some(l => l.message.includes('10.00'))).toBe(true);
  });

  it('dispatches tilt step', async () => {
    mockExecuteSimple.mockResolvedValue({
      new_position: { a: 15, b: -10 },
    } as any);

    const plan: ExecutionPlan = {
      plan_type: 'tilt',
      summary: 'Set tilt',
      steps: [{ action: 'tilt', params: { a: 15, b: -10 }, description: 'Tilt stage' }],
    };

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('', plan);
    });

    expect(mockExecuteSimple).toHaveBeenCalledWith('tilt', { a: 15, b: -10 });
  });

  it('dispatches set_mode step via raw fetch', async () => {
    // set_mode uses raw fetch, not executeSimple
    mockExecuteSimple.mockResolvedValue({} as any);

    const plan: ExecutionPlan = {
      plan_type: 'mode_switch',
      summary: 'Switch to diffraction',
      steps: [{ action: 'set_mode', params: { mode: 'DIFF' }, description: 'Switch mode' }],
    };

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('', plan);
    });

    // Should have called fetch for /api/microscope/execute
    const fetchCalls = mockFetch.mock.calls.filter(c =>
      typeof c[0] === 'string' && c[0].includes('/microscope/execute'),
    );
    expect(fetchCalls.length).toBeGreaterThanOrEqual(1);
    const body = JSON.parse(fetchCalls[fetchCalls.length - 1][1].body);
    expect(body.command).toBe('set_mode');
    expect(body.params.mode).toBe('DIFF');
  });

  it('handles step failure gracefully', async () => {
    mockExecuteSimple.mockRejectedValue(new Error('network down'));

    const plan: ExecutionPlan = {
      plan_type: 'test',
      summary: 'Test failure',
      steps: [{ action: 'move', params: { x_um: 1 }, description: 'Move' }],
    };

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('', plan);
    });

    // Should have error logs but still complete
    const errorLogs = result.current.executionLogs.filter(l => l.type === 'error');
    expect(errorLogs.length).toBeGreaterThan(0);
    expect(result.current.isExecuting).toBe(false);
  });

  it('logs unknown action and skips', async () => {
    const plan: ExecutionPlan = {
      plan_type: 'test',
      summary: 'Unknown',
      steps: [{ action: 'unknown_action', params: {}, description: 'Something' }],
    };

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode('', plan);
    });

    const infoLogs = result.current.executionLogs.filter(l => l.type === 'info');
    expect(infoLogs.some(l => l.message.includes('Unknown action'))).toBe(true);
  });
});

// --------------- regex fallback ---------------

describe('regex fallback (no plan)', () => {
  const connectedStatus = {
    connected: true,
    state: { sample_type: 'au_nanoparticles', mode: 'IMG', stage: { a: 0, b: 0 } },
  };

  beforeEach(() => {
    mockGetStatus.mockResolvedValue(connectedStatus as any);
    mockExecuteSimple.mockResolvedValue({
      image: { image_base64: 'data:test' },
      stage: { x_um: 0, y_um: 0, z_um: 0 },
    } as any);
  });

  it('detects grid scan from code', async () => {
    const code = `
grid_rows = 2
grid_cols = 2
step_size_um = 5.0
autofocus_enabled = True
    `;

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode(code);
    });

    const infoLogs = result.current.executionLogs.filter(l => l.type === 'info');
    expect(infoLogs.some(l => l.message.includes('grid scan'))).toBe(true);
  });

  it('detects tilt scan from code', async () => {
    const code = `
# Explore different tilt angles
alpha_angles = [0, 15, 30]
beta_angles = [0, 15]
    `;

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode(code);
    });

    const infoLogs = result.current.executionLogs.filter(l => l.type === 'info');
    expect(infoLogs.some(l => l.message.includes('tilt exploration'))).toBe(true);
  });

  it('falls back to line-by-line for simple code', async () => {
    const code = `
stem.acquire_image("haadf")
    `;

    const { result } = renderExecutionHook();

    await act(async () => {
      await result.current.handleRunCode(code);
    });

    // Should have command logs from line-by-line parsing
    const commandLogs = result.current.executionLogs.filter(l => l.type === 'command');
    expect(commandLogs.some(l => l.message.includes('Acquiring image'))).toBe(true);
  });
});
