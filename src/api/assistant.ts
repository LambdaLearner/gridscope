/**
 * API client for the GridScope AI Assistant backend
 */

import { ExperimentConfig } from '../types/config';

const API_BASE_URL = 'http://localhost:8000/api';

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  experiment_config?: ExperimentConfig | null;
  context?: string;
}

export interface ChatResponse {
  message: string;
  suggested_actions: string[];
  generated_code?: string;
  explanation?: string;
}

export interface CodeGenerationRequest {
  objective: string;
  experiment_config?: ExperimentConfig | null;
  microscope_type: string;
  software_api: string;
  additional_requirements?: string;
}

export interface CodeGenerationResponse {
  code: string;
  explanation: string;
  warnings: string[];
  suggested_modifications: string[];
}

export interface ApiTemplate {
  id: string;
  name: string;
  description: string;
}

export interface SupportedApi {
  id: string;
  name: string;
  microscopes: string[];
  install: string;
}

/**
 * Send a chat message to the AI assistant
 */
export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Chat request failed');
  }

  return response.json();
}

/**
 * Analyze an experimental objective
 */
export async function analyzeObjective(objective: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE_URL}/chat/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(objective),
  });

  if (!response.ok) {
    throw new Error('Analysis request failed');
  }

  return response.json();
}

/**
 * Get quick help on a microscopy topic
 */
export async function getQuickHelp(topic: string): Promise<{ topic: string; explanation: string }> {
  const response = await fetch(`${API_BASE_URL}/chat/quick-help`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(topic),
  });

  if (!response.ok) {
    throw new Error('Help request failed');
  }

  return response.json();
}

/**
 * Generate Python automation code
 */
export async function generateCode(request: CodeGenerationRequest): Promise<CodeGenerationResponse> {
  const response = await fetch(`${API_BASE_URL}/code/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Code generation failed');
  }

  return response.json();
}

/**
 * Generate raw Python code (for download)
 */
export async function generateCodeRaw(request: CodeGenerationRequest): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/code/generate/raw`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Code generation failed');
  }

  return response.text();
}

/**
 * Get list of available code templates
 */
export async function getTemplates(): Promise<{ templates: ApiTemplate[] }> {
  const response = await fetch(`${API_BASE_URL}/code/templates`);

  if (!response.ok) {
    throw new Error('Failed to fetch templates');
  }

  return response.json();
}

/**
 * Get list of supported microscopy APIs
 */
export async function getSupportedApis(): Promise<{ apis: SupportedApi[] }> {
  const response = await fetch(`${API_BASE_URL}/code/apis`);

  if (!response.ok) {
    throw new Error('Failed to fetch supported APIs');
  }

  return response.json();
}

/**
 * Check if the backend is healthy
 */
export async function checkHealth(): Promise<{ status: string; service: string }> {
  const response = await fetch('http://localhost:8000/health');

  if (!response.ok) {
    throw new Error('Backend is not healthy');
  }

  return response.json();
}

