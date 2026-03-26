"""Tests for backend/app/constants.py — validate shared constants."""

from app.constants import (
    DEFAULT_DETECTOR,
    MICROSCOPE_API_SPEC,
    WORKFLOW_TEMPLATES,
    TEM_CLIENT_SOURCE_PATH,
)


class TestDefaultDetector:
    def test_default_detector_is_haadf(self):
        assert DEFAULT_DETECTOR == "haadf"

    def test_default_detector_is_lowercase(self):
        assert DEFAULT_DETECTOR == DEFAULT_DETECTOR.lower()


class TestMicroscopeApiSpec:
    def test_spec_is_nonempty_string(self):
        assert isinstance(MICROSCOPE_API_SPEC, str)
        assert len(MICROSCOPE_API_SPEC) > 100

    def test_spec_contains_all_core_methods(self):
        required_methods = [
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
        for method in required_methods:
            assert method in MICROSCOPE_API_SPEC, f"Missing method: {method}"

    def test_spec_contains_extended_methods(self):
        extended_methods = [
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
        for method in extended_methods:
            assert method in MICROSCOPE_API_SPEC, f"Missing extended method: {method}"

    def test_spec_mentions_haadf_detector(self):
        assert "haadf" in MICROSCOPE_API_SPEC

    def test_spec_mentions_meters_for_stage(self):
        assert "METERS" in MICROSCOPE_API_SPEC

    def test_spec_mentions_degrees_for_tilt(self):
        assert "DEGREES" in MICROSCOPE_API_SPEC


class TestWorkflowTemplates:
    def test_templates_is_dict(self):
        assert isinstance(WORKFLOW_TEMPLATES, dict)

    def test_expected_keys_present(self):
        expected = ["tilt_series", "diffraction_scan", "beam_sweep", "mode_switch"]
        for key in expected:
            assert key in WORKFLOW_TEMPLATES, f"Missing template: {key}"

    def test_each_template_is_nonempty_string(self):
        for key, value in WORKFLOW_TEMPLATES.items():
            assert isinstance(value, str), f"Template {key} is not a string"
            assert len(value) > 10, f"Template {key} is too short"

    def test_tilt_series_uses_set_tilt(self):
        assert "set_tilt" in WORKFLOW_TEMPLATES["tilt_series"]

    def test_diffraction_scan_uses_set_mode(self):
        assert 'set_mode("DIFF")' in WORKFLOW_TEMPLATES["diffraction_scan"]

    def test_beam_sweep_uses_set_beam(self):
        assert "set_beam" in WORKFLOW_TEMPLATES["beam_sweep"]


class TestTemClientSourcePath:
    def test_path_points_to_existing_file(self):
        assert TEM_CLIENT_SOURCE_PATH.exists(), (
            f"tem_client.py not found at {TEM_CLIENT_SOURCE_PATH}"
        )

    def test_source_contains_stemclient_class(self):
        source = TEM_CLIENT_SOURCE_PATH.read_text()
        assert "class STEMClient" in source
