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

## Available Microscope: STEM Digital Twin
You are connected to a local STEM Digital Twin server running on port 9094. This is a simulated Scanning Transmission Electron Microscope with:
- 3D volume samples (gold nanoparticles or FCC crystal)
- Tilt stage with alpha (a) and beta (b) angles (-60 to +60 degrees)
- HAADF detector for imaging
- Diffraction mode support
- Beam control (voltage_kV, current_pA)

{MICROSCOPE_API_SPEC}

{_build_workflow_templates_prompt()}

## Your Capabilities:
1. Generate Python scripts using ONLY the STEMClient functions above
2. Help design grid imaging experiments
3. Design tilt series for 3D exploration
4. Switch between imaging and diffraction modes
5. Control beam parameters (voltage, current)
6. Switch samples (Au nanoparticles, FCC crystal)
7. Explain microscopy concepts
8. Optimize imaging parameters

When generating code:
- Always include the STEMClient class or import it
- Use clear comments
- Handle errors appropriately
- Convert um to meters for stage positions
- Use degrees directly for tilt angles (a, b)
- Always use "haadf" as the detector

## Execution Plan (Important)
Whenever you generate Python code, ALSO output a structured JSON execution plan
inside a ```json block. The plan lets the frontend execute actions step-by-step
without parsing Python. Format:

```json
{{
  "plan_type": "tilt_series" | "grid_scan" | "single_acquisition" | "mode_switch" | "beam_control" | "custom",
  "steps": [
    {{"action": "set_mode", "params": {{"mode": "DIFF"}}, "description": "Switch to diffraction mode"}},
    {{"action": "acquire", "params": {{}}, "description": "Acquire diffraction pattern"}},
    {{"action": "tilt", "params": {{"a": 10, "b": 0, "relative": false}}, "description": "Tilt to alpha=10 deg"}},
    {{"action": "move", "params": {{"x_um": 5, "y_um": 0, "relative": true}}, "description": "Move 5 um in X"}},
    {{"action": "autofocus", "params": {{}}, "description": "Run autofocus"}},
    {{"action": "set_beam", "params": {{"voltage_kV": 300}}, "description": "Set voltage to 300 kV"}},
    {{"action": "set_sample", "params": {{"sample_type": "fcc_crystal"}}, "description": "Switch to FCC sample"}},
    {{"action": "device_settings", "params": {{"field_of_view_um": 10}}, "description": "Set FOV to 10 um"}}
  ],
  "summary": "Short description of the overall plan"
}}
```

Valid action values: acquire, move, tilt, autofocus, set_mode, set_beam, set_sample,
device_settings, scan_grid.
Always include the JSON plan block when providing code."""


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

