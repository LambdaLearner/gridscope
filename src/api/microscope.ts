import { ExperimentConfig, StagePosition } from '../types/config';

export async function connectMicroscope(): Promise<{ success: boolean; message: string }> {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return {
    success: true,
    message: 'Connected to microscope',
  };
}

export async function disconnectMicroscope(): Promise<{ success: boolean }> {
  await new Promise((resolve) => setTimeout(resolve, 500));
  return { success: true };
}

export async function getCurrentStagePosition(): Promise<StagePosition> {
  await new Promise((resolve) => setTimeout(resolve, 300));
  return {
    x: Math.random() * 1000,
    y: Math.random() * 1000,
  };
}

export async function startRun(config: ExperimentConfig): Promise<{ success: boolean; runId: string }> {
  await new Promise((resolve) => setTimeout(resolve, 500));
  console.log('Starting run with config:', config);
  return {
    success: true,
    runId: `run_${Date.now()}`,
  };
}
