"""Tests for llm_agent.py — the SYSTEM_PROMPT must describe the portable
control surface (and only that surface)."""

from app.constants import DEFAULT_DETECTOR
from app.services.llm_agent import SYSTEM_PROMPT


class TestSystemPrompt:
    def test_prompt_is_nonempty(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 200

    def test_prompt_contains_control_methods(self):
        methods = [
            "is_ready",
            "get_detectors",
            "device_settings",
            "get_stage",
            "set_stage",
            "get_stage_limits",
            "get_magnification",
            "set_magnification",
            "get_beam",
            "set_beam",
            "set_mode",
            "get_mode",
            "set_diffraction_settings",
            "acquire_image",
            "autofocus",
            "get_microscope_state",
        ]
        for method in methods:
            assert method in SYSTEM_PROMPT, f"Missing control method: {method}"

    def test_prompt_forbids_simulation_code(self):
        # The prompt may EXPLAIN that samples/environments are UI-only, but it
        # must never document simulation calls as usable API.
        for forbidden in ["mic.load_sample", "mic.set_environment",
                          "mic.set_drift", "mic.set_specimen",
                          "SimulationHarness(", "STEMClient"]:
            assert forbidden not in SYSTEM_PROMPT, f"Found: {forbidden}"

    def test_prompt_mentions_safety_limits(self):
        assert "SAFETY LIMITS" in SYSTEM_PROMPT or "safety limits" in SYSTEM_PROMPT

    def test_prompt_mentions_autofocus_failure(self):
        assert "converged" in SYSTEM_PROMPT

    def test_prompt_mentions_report_image(self):
        assert "report_image" in SYSTEM_PROMPT

    def test_prompt_mentions_correct_detector(self):
        assert DEFAULT_DETECTOR in SYSTEM_PROMPT

    def test_prompt_contains_workflow_templates(self):
        assert "Tilt Series" in SYSTEM_PROMPT
        assert "Diffraction Scan" in SYSTEM_PROMPT
        assert "Grid Scan" in SYSTEM_PROMPT

    def test_prompt_does_not_mention_flu_camera(self):
        assert "flu_camera" not in SYSTEM_PROMPT
