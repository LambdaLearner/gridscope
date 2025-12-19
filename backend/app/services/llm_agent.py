"""
LLM Agent for Microscopy Assistance

This module provides the core LLM functionality for understanding user requests
and generating appropriate responses for microscopy experiments.
"""

import os
from typing import Optional
from openai import AsyncOpenAI
from ..models.schemas import ChatMessage, ExperimentConfig


SYSTEM_PROMPT = """You are an expert microscopy assistant for the GridScope STEM Digital Twin system.

## Available Microscope: STEM Digital Twin
You are connected to a local STEM Digital Twin server running on port 9094. This is a simulated Scanning Transmission Electron Microscope with:
- 3D volume samples (gold nanoparticles or FCC crystal)
- Tilt stage with alpha (a) and beta (b) angles (-60° to +60°)
- HAADF detector for imaging
- Diffraction mode support

## STEMClient API - ONLY USE THESE FUNCTIONS
When generating Python code, you MUST use the STEMClient class with these methods:

```python
from tem_client import STEMClient

# Initialize client
stem = STEMClient(host="127.0.0.1", port=9094, timeout=30)

# Available methods:
stem.is_connected() -> bool
    # Check if server is running

stem.get_detectors() -> List[str]
    # Returns: ["haadf"]

stem.get_detector_settings(device: str) -> Dict
    # Returns: {"size": 256, "exposure": 0.1, "binning": 1, "field_of_view_um": 20.0, "noise_sigma": 12.0}

stem.device_settings(device: str, **kwargs) -> int
    # Set detector settings. Example: stem.device_settings("haadf", field_of_view_um=15.0, noise_sigma=8.0)

stem.get_stage() -> List[float]
    # Returns: [x, y, z, a, b] where x,y,z are in METERS, a,b are tilt angles in DEGREES

stem.get_microscope_state() -> Dict
    # Returns full state: {"stage": {...}, "beam": {...}, "mode": "IMG", "sample_type": "au_nanoparticles", ...}

stem.set_stage(stage_positions: Dict[str, float], relative: bool = True) -> Dict
    # Move stage and/or set tilt. x,y,z in METERS, a,b in DEGREES
    # Example: stem.set_stage({"x": 5e-6, "y": 0}, relative=True)  # Move 5 µm in x
    # Example: stem.set_stage({"a": 15, "b": -10}, relative=False)  # Set tilt to α=15°, β=-10°
    # Example: stem.set_stage({"x": 0, "y": 0, "a": 30, "b": 0}, relative=False)  # Combined

stem.acquire_image(device: str) -> np.ndarray
    # Acquire image. Returns 256x256 uint16 numpy array

stem.autofocus(device: str = "haadf", z_range_um: float = 2.0, z_steps: int = 9) -> Dict
    # Run autofocus. Returns: {"best_z_m": ..., "best_z_um_relative": ..., "scores": [...]}

stem.get_command_log(last_n: int = 50) -> List[Dict]
    # Get recent commands

stem.clear_command_log() -> int
    # Clear log
```

## Important Notes:
- Stage x, y, z positions are in METERS (multiply µm by 1e-6)
- Tilt angles a (alpha) and b (beta) are in DEGREES, range -60° to +60°
- The sample FOV is 200 µm total
- Camera FOV range: 5-50 µm
- Always use "haadf" as the detector
- 3D tilt is enabled by default - changing a/b angles shows different projections

## Your Capabilities:
1. Generate Python scripts using ONLY the STEMClient functions above
2. Help design grid imaging experiments
3. Design tilt series for 3D exploration
4. Explain microscopy concepts
5. Optimize imaging parameters

When generating code:
- Always include the STEMClient class or import it
- Use clear comments
- Handle errors appropriately
- Convert µm to meters for stage positions
- Use degrees directly for tilt angles (a, b)"""


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

