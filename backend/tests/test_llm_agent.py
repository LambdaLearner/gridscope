"""Tests for llm_agent.py — verify SYSTEM_PROMPT has full API."""

from app.services.llm_agent import SYSTEM_PROMPT
from app.constants import DEFAULT_DETECTOR


class TestSystemPrompt:
    def test_prompt_is_nonempty(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 200

    def test_prompt_contains_all_core_methods(self):
        methods = [
            "is_connected",
            "get_detectors",
            "get_detector_settings",
            "device_settings",
            "get_stage",
            "set_stage",
            "get_microscope_state",
            "acquire_image",
            "autofocus",
            "get_command_log",
            "clear_command_log",
        ]
        for method in methods:
            assert method in SYSTEM_PROMPT, f"Missing core method: {method}"

    def test_prompt_contains_extended_methods(self):
        extended = [
            "set_mode",
            "get_mode",
            "set_beam",
            "get_beam",
            "set_tilt",
            "get_tilt",
            "set_sample_type",
            "get_sample_type",
            "set_diffraction_settings",
            "get_diffraction_settings",
        ]
        for method in extended:
            assert method in SYSTEM_PROMPT, f"Missing extended method: {method}"

    def test_prompt_mentions_correct_detector(self):
        assert DEFAULT_DETECTOR in SYSTEM_PROMPT

    def test_prompt_contains_workflow_templates(self):
        assert "Tilt Series" in SYSTEM_PROMPT
        assert "Diffraction Scan" in SYSTEM_PROMPT
        assert "Beam Sweep" in SYSTEM_PROMPT
        assert "Mode Switch" in SYSTEM_PROMPT

    def test_prompt_does_not_mention_flu_camera(self):
        assert "flu_camera" not in SYSTEM_PROMPT
