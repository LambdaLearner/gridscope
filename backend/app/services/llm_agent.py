"""
LLM Agent for Microscopy Assistance

This module provides the core LLM functionality for understanding user requests
and generating appropriate responses for microscopy experiments.
"""

import os
from typing import Optional
from openai import AsyncOpenAI
from ..models.schemas import ChatMessage, ExperimentConfig
from ..constants import MICROSCOPE_API_SPEC, WORKFLOW_TEMPLATES


def _build_workflow_templates_prompt() -> str:
    """Format workflow templates for inclusion in the system prompt."""
    parts = ["\n## Workflow Templates\nUse these patterns for common tasks:\n"]
    for name, code in WORKFLOW_TEMPLATES.items():
        label = name.replace("_", " ").title()
        parts.append(f"### {label}\n```python\n{code}```\n")
    return "\n".join(parts)


SYSTEM_PROMPT = f"""You are an expert microscopy assistant for the GridScope STEM Digital Twin system.

## Available Microscope: STEM Digital Twin (v6)
You are connected to a local STEM Digital Twin server on port 9094 — a
simulated Scanning Transmission Electron Microscope used to develop and
stress-test automation scripts before deployment on a real instrument:
- HAADF detector; imaging (IMG) and diffraction (DIFF) modes, with diffraction
  computed from atomic positions (crystals → spots, polycrystals → rings,
  amorphous → diffuse halos)
- Double-tilt stage with SOFT SAFETY LIMITS: ±1.5 mm (x/y), ±1 mm (z),
  ±30° (a/b tilt); out-of-range moves are rejected and the stage does not move
- Magnification ↔ field-of-view control (mag = k / FOV)
- Beam control (voltage_kV, current_pA); autofocus that can legitimately fail

The specimen is chosen by the user in the Sample Settings window BEFORE any
script runs (a registry of 13 samples: crystals, polycrystals, dislocations,
amorphous films, Au nanoparticle variants, core-shell, and more). Simulation
realism (environments, drift, beam damage, contamination) is likewise
configured in the UI. NONE of that appears in scripts: generated code uses
only operations a real microscope has, so it can be deployed unchanged.

{MICROSCOPE_API_SPEC}

{_build_workflow_templates_prompt()}

## Your Capabilities:
1. Generate Python scripts using ONLY the MicroscopeControlClient API above
2. Help design grid imaging experiments and tilt series
3. Switch between imaging and diffraction modes; tune diffraction projection
4. Control beam parameters and magnification
5. Explain microscopy concepts and optimize imaging parameters

When generating code:
- Write against MicroscopeControlClient; do NOT redefine the class or open a
  connection — the runner prepends the class, a report_image(img, **meta)
  helper, AND a ready `mic = MicroscopeControlClient(host="127.0.0.1",
  port=9094)` instance automatically. Just use `mic` directly.
- NEVER select samples/environments/drift/damage in code — UI-only concepts
- Convert µm to metres for stage positions; tilt angles in degrees
- Handle stage-limit rejections (RuntimeError from set_stage) and autofocus
  non-convergence (result["converged"] is False)
- Call report_image(img, ...) after every acquire_image so frames stream to
  the GridScope UI
- Always use "haadf" as the detector"""


class LLMAgent:
    """LLM Agent for microscopy assistance."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the LLM agent.
        
        Args:
            api_key: OpenAI API key. If not provided, reads from OPENAI_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable.")
        
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")

    def _build_context(self, experiment_config: Optional[ExperimentConfig] = None) -> str:
        """Build context string from experiment configuration."""
        if not experiment_config:
            return ""
        
        context_parts = [
            "\n\nCurrent Experiment Configuration:",
            f"- Field of View: {experiment_config.fov} {experiment_config.fov_unit}",
            f"- Voltage: {experiment_config.voltage_kv} kV",
            f"- Current: {experiment_config.current_value} {experiment_config.current_unit}",
            f"- Grid: {experiment_config.grid.rows}x{experiment_config.grid.cols} tiles",
            f"- Overlap: {experiment_config.grid.overlap_percent}%",
            f"- Step Size: {experiment_config.grid.step_size} µm",
            f"- Start Position: ({experiment_config.start_pos.x}, {experiment_config.start_pos.y})",
            f"- Autofocus: {'Enabled' if experiment_config.autofocus_each_tile else 'Disabled'}",
            f"- Aberration Correction: {'Enabled' if experiment_config.auto_aberration_each_tile else 'Disabled'}",
            f"- Dwell Time: {experiment_config.dwell_s}s",
        ]
        
        return "\n".join(context_parts)

    async def chat(
        self,
        messages: list[ChatMessage],
        experiment_config: Optional[ExperimentConfig] = None,
        additional_context: Optional[str] = None,
    ) -> str:
        """Process a chat conversation and return a response.
        
        Args:
            messages: List of chat messages in the conversation
            experiment_config: Optional current experiment configuration for context
            additional_context: Any additional context to include
            
        Returns:
            The assistant's response message
        """
        # Build system message with context
        system_content = SYSTEM_PROMPT
        
        if experiment_config:
            system_content += self._build_context(experiment_config)
        
        if additional_context:
            system_content += f"\n\nAdditional Context:\n{additional_context}"

        # Convert messages to OpenAI format
        openai_messages = [{"role": "system", "content": system_content}]
        
        for msg in messages:
            openai_messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # Call OpenAI API
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            temperature=0.7,
            max_tokens=2000,
        )

        return response.choices[0].message.content or ""

    async def analyze_objective(self, objective: str) -> dict:
        """Analyze a user's experimental objective and extract key parameters.
        
        Args:
            objective: The user's description of what they want to accomplish
            
        Returns:
            Dictionary with extracted parameters and suggestions
        """
        analysis_prompt = f"""Analyze this microscopy experiment objective and extract key parameters:

Objective: {objective}

Respond in this exact JSON format:
{{
    "sample_type": "description of the sample",
    "imaging_mode": "SEM/TEM/FIB-SEM/etc",
    "suggested_voltage_kv": number or null,
    "suggested_current": "value with unit" or null,
    "suggested_magnification": number or null,
    "automation_needed": true/false,
    "grid_imaging": true/false,
    "special_requirements": ["list", "of", "requirements"],
    "clarifying_questions": ["questions", "to", "ask"]
}}"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a microscopy expert. Respond only with valid JSON."},
                {"role": "user", "content": analysis_prompt}
            ],
            temperature=0.3,
            max_tokens=500,
        )

        import json
        try:
            return json.loads(response.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            return {"error": "Failed to parse analysis", "raw": response.choices[0].message.content}

