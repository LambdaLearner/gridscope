/**
 * useCodeExecution — hook that encapsulates all code-execution logic.
 *
 * Supports two execution paths:
 *  1. Plan-based dispatch: iterate ExecutionPlan.steps and dispatch each by action.
 *  2. Regex fallback: detect tilt scans / grid scans from generated Python code.
 */

import { useState, useCallback } from 'react';
import { getMicroscopeStatus } from '../api/digitalTwin';
import { executeSimple } from '../api/execute';
import type { ExecutionLog, AcquiredImage, ExecutionPlan } from '../types/execution';

export interface UseCodeExecutionReturn {
  executionLogs: ExecutionLog[];
  acquiredImages: AcquiredImage[];
  isExecuting: boolean;
  handleRunCode: (code: string, executionPlan?: ExecutionPlan) => Promise<void>;
  clearResults: () => void;
}

export function useCodeExecution(
  currentSampleType: string,
  currentMode: string,
  setCurrentSampleType: (v: string) => void,
  setCurrentMode: (v: string) => void,
): UseCodeExecutionReturn {
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [acquiredImages, setAcquiredImages] = useState<AcquiredImage[]>([]);
  const [isExecuting, setIsExecuting] = useState(false);

  const addLog = (type: ExecutionLog['type'], message: string, data?: ExecutionLog['data']) => {
    setExecutionLogs(prev => [...prev, {
      id: Date.now().toString() + Math.random().toString(36).slice(2, 6),
      type,
      message,
      timestamp: new Date(),
      data,
    }]);
  };

  const clearResults = useCallback(() => {
    setExecutionLogs([]);
    setAcquiredImages([]);
  }, []);

  // ---- helpers ----

  const fetchState = async () => {
    let info = {
      sampleType: currentSampleType, mode: currentMode,
      a: 0, b: 0,
      voltage_kV: 0, current_pA: 0, fov_um: 0,
    };
    try {
      const status = await getMicroscopeStatus();
      if (status.state) {
        info = {
          sampleType: status.state.sample_type || currentSampleType,
          mode: status.state.mode || currentMode,
          a: status.state.stage?.a || 0,
          b: status.state.stage?.b || 0,
          voltage_kV: status.state.beam?.voltage_kV || 0,
          current_pA: status.state.beam?.current_pA || 0,
          fov_um: status.state.detectors?.haadf?.field_of_view_um || 0,
        };
        setCurrentSampleType(info.sampleType);
        setCurrentMode(info.mode);
      }
    } catch { /* ignore */ }
    return info;
  };

  const acquireAndAddImage = async (label?: string) => {
    const stateInfo = await fetchState();
    try {
      const result = await executeSimple<{
        image?: { image_base64?: string };
        stage: { x_um: number; y_um: number; z_um: number };
      }>('acquire', {});
      if (result.image?.image_base64) {
        setAcquiredImages(prev => [...prev, {
          image_base64: result.image!.image_base64!,
          x_um: result.stage.x_um,
          y_um: result.stage.y_um,
          z_um: result.stage.z_um,
          a: stateInfo.a,
          b: stateInfo.b,
          sampleType: stateInfo.sampleType,
          mode: stateInfo.mode,
          voltage_kV: stateInfo.voltage_kV,
          current_pA: stateInfo.current_pA,
          fov_um: stateInfo.fov_um,
        }]);
        addLog('image', label || `Image acquired at (${result.stage.x_um.toFixed(2)}, ${result.stage.y_um.toFixed(2)}) um`, {
          image_base64: result.image.image_base64,
          stage: { ...result.stage, a: stateInfo.a, b: stateInfo.b },
          sampleType: stateInfo.sampleType,
          mode: stateInfo.mode,
          voltage_kV: stateInfo.voltage_kV,
          current_pA: stateInfo.current_pA,
          fov_um: stateInfo.fov_um,
        });
        return result;
      }
    } catch { /* acquire failed */ }
    return null;
  };

  // ---- plan-based dispatch ----

  const executePlan = async (plan: ExecutionPlan) => {
    addLog('info', `Executing plan: ${plan.summary || plan.plan_type} (${plan.steps.length} steps)`);

    for (let i = 0; i < plan.steps.length; i++) {
      const step = plan.steps[i];
      const prefix = `[${i + 1}/${plan.steps.length}]`;
      addLog('command', `${prefix} ${step.description || step.action}`);

      try {
        switch (step.action) {
          case 'acquire': {
            await acquireAndAddImage(`${prefix} Image acquired`);
            break;
          }
          case 'move': {
            const r = await executeSimple<{ new_position?: { x_um?: number; y_um?: number; z_um?: number } }>(
              'move', step.params,
            );
            addLog('success', `Stage at (${r.new_position?.x_um?.toFixed(2)}, ${r.new_position?.y_um?.toFixed(2)}) um`);
            break;
          }
          case 'tilt': {
            const r = await executeSimple<{ new_position?: { a?: number; b?: number } }>(
              'tilt', step.params,
            );
            addLog('success', `Tilt set to a=${r.new_position?.a?.toFixed(1)} deg, b=${r.new_position?.b?.toFixed(1)} deg`);
            break;
          }
          case 'autofocus': {
            const r = await executeSimple<{ result?: { best_z_um_relative?: number } }>(
              'autofocus', step.params,
            );
            addLog('success', `Autofocus: Z adjusted by ${r.result?.best_z_um_relative?.toFixed(2) || 0} um`);
            break;
          }
          case 'set_mode': {
            await executeSimple('acquire', {}); // no-op to force state refresh
            // Use the microscope execute command endpoint
            const mode = (step.params.mode as string) || 'IMG';
            await fetch('http://localhost:8000/api/microscope/execute', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ command: 'set_mode', params: { mode } }),
            });
            addLog('success', `Mode set to ${mode}`);
            break;
          }
          case 'set_beam': {
            await fetch('http://localhost:8000/api/microscope/execute', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ command: 'set_beam', params: { beam_settings: step.params } }),
            });
            addLog('success', `Beam settings updated`);
            break;
          }
          case 'set_sample': {
            const sampleType = (step.params.sample_type as string) || 'au_nanoparticles';
            await fetch('http://localhost:8000/api/microscope/execute', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ command: 'set_sample_type', params: { sample_type: sampleType } }),
            });
            setCurrentSampleType(sampleType);
            addLog('success', `Sample set to ${sampleType}`);
            break;
          }
          case 'device_settings': {
            const fov = step.params.field_of_view_um;
            if (fov) {
              await executeSimple('acquire', { fov_um: fov });
              addLog('success', `FOV set to ${fov} um`);
            }
            break;
          }
          case 'scan_grid': {
            const r = await executeSimple<{ total_tiles: number }>('scan_grid', step.params);
            addLog('success', `Grid scan complete: ${r.total_tiles} tiles`);
            break;
          }
          default:
            addLog('info', `Unknown action: ${step.action}, skipping`);
        }
      } catch (e) {
        addLog('error', `Step failed: ${step.action} — ${e}`);
      }

      await new Promise(r => setTimeout(r, 100));
    }

    addLog('success', `Plan execution complete!`);
  };

  // ---- regex-based detection helpers ----

  const detectTiltScan = (code: string): { alphaValues: number[]; betaValues: number[] } | null => {
    const isTiltExploration = /(?:explore|vary|different|scan|series).*(?:tilt|alpha|beta|a\s+and\s+b)/i.test(code);

    let alphaValues: number[] = [];
    let betaValues: number[] = [];

    const alphaListMatch = code.match(/alpha_?(?:angles?|values?)?\s*=\s*\[([^\]]+)\]/i);
    const betaListMatch = code.match(/beta_?(?:angles?|values?)?\s*=\s*\[([^\]]+)\]/i);
    const aListMatch = code.match(/\ba\s*=\s*\[([^\]]+)\]/);
    const bListMatch = code.match(/\bb\s*=\s*\[([^\]]+)\]/);

    const alphaSource = alphaListMatch?.[1] || aListMatch?.[1];
    if (alphaSource) {
      alphaValues = alphaSource.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    }
    const betaSource = betaListMatch?.[1] || bListMatch?.[1];
    if (betaSource) {
      betaValues = betaSource.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    }

    if (alphaValues.length === 0 || betaValues.length === 0) {
      const rangeMatch = code.match(/(?:a,?\s*b|alpha.*beta|tilt).*?(\d+)\s*(?:to|through|-)\s*(\d+).*?(?:step|increment)\s*(?:of\s*)?(\d+)/i);
      if (rangeMatch) {
        const start = parseInt(rangeMatch[1]);
        const end = parseInt(rangeMatch[2]);
        const step = parseInt(rangeMatch[3]);
        const values: number[] = [];
        for (let v = start; v <= end; v += step) values.push(v);
        if (alphaValues.length === 0) alphaValues = values;
        if (betaValues.length === 0) betaValues = values;
      }
    }

    if (alphaValues.length === 0) {
      const alphaRangeMatch = code.match(/alpha_?(?:angles?|values?)?\s*=\s*(?:list\()?(?:range|np\.arange)\((\d+),\s*(\d+),?\s*(\d+)?\)/i);
      if (alphaRangeMatch) {
        const start = parseInt(alphaRangeMatch[1]);
        const end = parseInt(alphaRangeMatch[2]);
        const step = alphaRangeMatch[3] ? parseInt(alphaRangeMatch[3]) : 1;
        for (let v = start; v < end; v += step) alphaValues.push(v);
      }
    }
    if (betaValues.length === 0) {
      const betaRangeMatch = code.match(/beta_?(?:angles?|values?)?\s*=\s*(?:list\()?(?:range|np\.arange)\((\d+),\s*(\d+),?\s*(\d+)?\)/i);
      if (betaRangeMatch) {
        const start = parseInt(betaRangeMatch[1]);
        const end = parseInt(betaRangeMatch[2]);
        const step = betaRangeMatch[3] ? parseInt(betaRangeMatch[3]) : 1;
        for (let v = start; v < end; v += step) betaValues.push(v);
      }
    }

    if (isTiltExploration && alphaValues.length === 0 && betaValues.length === 0) {
      const stepMatch = code.match(/step\s*(?:of|=|:)?\s*(\d+)/i);
      const step = stepMatch ? parseInt(stepMatch[1]) : 15;
      const objRangeMatch = code.match(/(\d+)\s*(?:to|through|-)\s*(\d+)/);
      if (objRangeMatch) {
        const start = parseInt(objRangeMatch[1]);
        const end = parseInt(objRangeMatch[2]);
        for (let v = start; v <= end; v += step) {
          alphaValues.push(v);
          betaValues.push(v);
        }
      } else {
        alphaValues = [-30, -15, 0, 15, 30];
        betaValues = [-30, -15, 0, 15, 30];
      }
    }

    if (alphaValues.length > 0 || betaValues.length > 0) {
      if (alphaValues.length === 0) alphaValues = [0];
      if (betaValues.length === 0) betaValues = [0];
      return { alphaValues, betaValues };
    }
    return null;
  };

  const detectGridScan = (code: string): { rows: number; cols: number; step_um: number; fov_um: number; autofocus: boolean } | null => {
    const rowsMatch = code.match(/["']?grid_rows["']?\s*[:=]\s*(\d+)/i);
    const colsMatch = code.match(/["']?grid_cols["']?\s*[:=]\s*(\d+)/i);
    const stepMatch = code.match(/["']?step_size(?:_um)?["']?\s*[:=]\s*([\d.]+)/i);
    const fovMatch = code.match(/["']?field_of_view(?:_um)?["']?\s*[:=]\s*([\d.]+)/i);
    const autofocusMatch = code.match(/["']?autofocus(?:_enabled)?["']?\s*[:=]\s*(True|False|true|false)/i);
    const gridPatternMatch = code.match(/(\d+)\s*[xX\u00d7]\s*(\d+)\s*grid/i);
    const spacingMatch = code.match(/(\d+(?:\.\d+)?)\s*(?:µm|um|micrometer)/i);

    const rows = rowsMatch ? parseInt(rowsMatch[1]) : (gridPatternMatch ? parseInt(gridPatternMatch[1]) : 0);
    const cols = colsMatch ? parseInt(colsMatch[1]) : (gridPatternMatch ? parseInt(gridPatternMatch[2]) : 0);
    const step = stepMatch ? parseFloat(stepMatch[1]) : (spacingMatch ? parseFloat(spacingMatch[1]) : 10);
    const fov = fovMatch ? parseFloat(fovMatch[1]) : 20;
    const autofocus = autofocusMatch ? autofocusMatch[1].toLowerCase() === 'true' : true;

    if (rows > 0 && cols > 0) {
      return { rows, cols, step_um: step, fov_um: fov, autofocus };
    }
    return null;
  };

  // ---- regex fallback execution ----

  const executeViaRegex = async (code: string) => {
    // Check tilt scan
    const tiltParams = detectTiltScan(code);
    if (tiltParams) {
      const { alphaValues, betaValues } = tiltParams;
      const totalImages = alphaValues.length * betaValues.length;
      addLog('info', `Detected tilt exploration: ${totalImages} images`);

      let imgCount = 0;
      for (const alpha of alphaValues) {
        for (const beta of betaValues) {
          imgCount++;
          addLog('command', `[${imgCount}/${totalImages}] Setting tilt a=${alpha} deg, b=${beta} deg`);
          try {
            const r = await executeSimple<{ new_position?: { a?: number; b?: number } }>('tilt', { a: alpha, b: beta, relative: false });
            addLog('success', `Tilt set to a=${r.new_position?.a?.toFixed(1)} deg, b=${r.new_position?.b?.toFixed(1)} deg`);
          } catch {
            addLog('error', `Failed to set tilt a=${alpha} deg, b=${beta} deg`);
            continue;
          }
          await new Promise(r => setTimeout(r, 100));
          await acquireAndAddImage(`Image at a=${alpha} deg, b=${beta} deg`);
          await new Promise(r => setTimeout(r, 150));
        }
      }
      addLog('success', `Tilt exploration complete! Acquired ${totalImages} images.`);
      return;
    }

    // Check grid scan
    const gridParams = detectGridScan(code);
    if (gridParams) {
      const totalTiles = gridParams.rows * gridParams.cols;
      addLog('info', `Detected ${gridParams.rows}x${gridParams.cols} grid scan (step: ${gridParams.step_um} um)`);

      for (let row = 0; row < gridParams.rows; row++) {
        for (let col = 0; col < gridParams.cols; col++) {
          const tileIdx = row * gridParams.cols + col;
          const x_um = col * gridParams.step_um;
          const y_um = row * gridParams.step_um;

          addLog('command', `[${tileIdx + 1}/${totalTiles}] Moving to (${x_um.toFixed(1)}, ${y_um.toFixed(1)}) um`);
          try {
            const r = await executeSimple<{ new_position?: { x_um?: number; y_um?: number; z_um?: number } }>('move', { x_um, y_um, relative: false });
            addLog('success', `Stage at (${r.new_position?.x_um?.toFixed(2)}, ${r.new_position?.y_um?.toFixed(2)}) um`);
          } catch {
            addLog('error', `Failed to move to tile ${tileIdx + 1}`);
            continue;
          }

          if (gridParams.autofocus) {
            addLog('command', `[${tileIdx + 1}/${totalTiles}] Autofocusing...`);
            try {
              const af = await executeSimple<{ result?: { best_z_um_relative?: number } }>('autofocus', { z_range_um: 4.0, z_steps: 9 });
              addLog('success', `Focus adjusted by ${af.result?.best_z_um_relative?.toFixed(2) || 0} um`);
            } catch { /* non-fatal */ }
          }

          await acquireAndAddImage(`Tile ${tileIdx + 1}/${totalTiles} at (${x_um.toFixed(1)}, ${y_um.toFixed(1)}) um`);
          await new Promise(r => setTimeout(r, 100));
        }
      }
      addLog('success', `Grid scan complete! Acquired ${totalTiles} images.`);
      return;
    }

    // Line-by-line fallback
    addLog('info', 'Acquiring initial reference image...');
    await acquireAndAddImage('Initial reference image');
    await new Promise(r => setTimeout(r, 300));

    const lines = code.split('\n');
    let commandCount = 0;

    for (const line of lines) {
      if (!line.trim() || line.trim().startsWith('#')) continue;

      if (line.includes('acquire_image') && !line.includes('def ') && !line.includes('# ')) {
        commandCount++;
        addLog('command', `[${commandCount}] Acquiring image...`);
        await acquireAndAddImage();
        await new Promise(r => setTimeout(r, 300));
      }

      if (line.includes('set_stage') && !line.includes('def ')) {
        commandCount++;
        const xMatch = line.match(/["']?x["']?\s*:\s*(-?[\d.]+(?:e[+-]?\d+)?)/i);
        const yMatch = line.match(/["']?y["']?\s*:\s*(-?[\d.]+(?:e[+-]?\d+)?)/i);
        let dx_m = 0, dy_m = 0;
        let hasValidMove = false;
        const movements: string[] = [];

        if (xMatch) { dx_m = parseFloat(xMatch[1]); if (!isNaN(dx_m)) { movements.push(`x=${(dx_m * 1e6).toFixed(2)} um`); hasValidMove = true; } }
        if (yMatch) { dy_m = parseFloat(yMatch[1]); if (!isNaN(dy_m)) { movements.push(`y=${(dy_m * 1e6).toFixed(2)} um`); hasValidMove = true; } }

        if (hasValidMove) {
          addLog('command', `[${commandCount}] Moving stage: ${movements.join(', ')}`);
          try {
            const r = await executeSimple<{ new_position?: { x_um?: number; y_um?: number; z_um?: number } }>('move', { dx: dx_m, dy: dy_m });
            addLog('success', `Stage at (${r.new_position?.x_um?.toFixed(2) || 0}, ${r.new_position?.y_um?.toFixed(2) || 0}) um`);
            await new Promise(r => setTimeout(r, 100));
            await acquireAndAddImage('Image after move');
          } catch (e) {
            addLog('error', `Stage move failed: ${e}`);
          }
        }
        await new Promise(r => setTimeout(r, 200));
      }

      if (line.includes('autofocus') && !line.includes('def ') && !line.includes('autofocus_')) {
        commandCount++;
        addLog('command', `[${commandCount}] Running autofocus...`);
        try {
          const r = await executeSimple<{ result?: { best_z_um_relative?: number } }>('autofocus', { z_range_um: 4.0, z_steps: 9 });
          addLog('success', `Autofocus complete: Z adjusted by ${r.result?.best_z_um_relative?.toFixed(2) || 0} um`);
          await new Promise(r => setTimeout(r, 100));
          await acquireAndAddImage('Image after autofocus (in focus)');
        } catch {
          addLog('error', 'Autofocus failed');
        }
        await new Promise(r => setTimeout(r, 300));
      }

      if (line.includes('device_settings') && !line.includes('def ')) {
        commandCount++;
        const fovMatch = line.match(/field_of_view_um\s*[=:]\s*([\d.]+)/);
        if (fovMatch) {
          const fov = parseFloat(fovMatch[1]);
          addLog('command', `[${commandCount}] Setting FOV to ${fov} um`);
          try {
            await executeSimple('acquire', { fov_um: fov });
            addLog('success', `FOV updated to ${fov} um`);
          } catch (e) {
            addLog('error', `Failed to set FOV: ${e}`);
          }
        } else {
          addLog('command', `[${commandCount}] Updating device settings`);
        }
        await new Promise(r => setTimeout(r, 100));
      }
    }
    addLog('success', `Execution complete! ${commandCount} commands executed.`);
  };

  // ---- main entry point ----

  const handleRunCode = useCallback(async (code: string, executionPlan?: ExecutionPlan) => {
    setIsExecuting(true);
    setExecutionLogs([]);
    setAcquiredImages([]);
    addLog('info', 'Starting execution on STEM Digital Twin...');

    try {
      const status = await getMicroscopeStatus();
      if (!status.connected) {
        addLog('error', 'Digital Twin not connected. Please start the server.');
        setIsExecuting(false);
        return;
      }
      addLog('success', 'Connected to Digital Twin');

      if (executionPlan && executionPlan.steps.length > 0) {
        await executePlan(executionPlan);
      } else {
        await executeViaRegex(code);
      }
    } catch (error) {
      addLog('error', `Execution failed: ${error}`);
    } finally {
      setIsExecuting(false);
    }
  }, [currentSampleType, currentMode]);

  return {
    executionLogs,
    acquiredImages,
    isExecuting,
    handleRunCode,
    clearResults,
  };
}
