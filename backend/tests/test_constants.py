"""Tests for constants.py — including the spec-vs-client drift guard.

MICROSCOPE_API_SPEC is hand-written prose shown to the LLM; these tests make
drift from the real MicroscopeControlClient a test failure instead of a
silently wrong prompt.
"""

import re

from app.constants import (
    CONTROL_CLIENT_SOURCE_PATH,
    DEFAULT_DETECTOR,
    IMAGE_MARKER,
    MICROSCOPE_API_SPEC,
    WORKFLOW_TEMPLATES,
)
from app.digital_twin.control_client import MicroscopeControlClient


class TestDefaultDetector:
    def test_default_detector_is_haadf(self):
        assert DEFAULT_DETECTOR == "haadf"

    def test_default_detector_is_lowercase(self):
        assert DEFAULT_DETECTOR == DEFAULT_DETECTOR.lower()


class TestSpecMatchesControlClient:
    """The drift guard: every method the spec documents must exist on the
    client, and nothing simulation-only may appear in the spec."""

    def _spec_methods(self):
        return set(re.findall(r"mic\.(\w+)\(", MICROSCOPE_API_SPEC))

    def test_spec_documents_methods(self):
        assert len(self._spec_methods()) >= 15

    def test_every_documented_method_exists_on_client(self):
        for method in self._spec_methods():
            assert hasattr(MicroscopeControlClient, method), (
                f"MICROSCOPE_API_SPEC documents mic.{method}() but "
                f"MicroscopeControlClient has no such method"
            )

    def test_every_public_client_method_is_documented(self):
        public = {
            name for name in vars(MicroscopeControlClient)
            if not name.startswith("_")
            and callable(getattr(MicroscopeControlClient, name))
        }
        undocumented = public - self._spec_methods()
        assert not undocumented, (
            f"Control-client methods missing from MICROSCOPE_API_SPEC: {undocumented}"
        )

    def test_spec_never_mentions_simulation_surface(self):
        for forbidden in ["SimulationHarness", "load_sample", "set_environment",
                          "set_drift", "set_specimen", "reset_specimen",
                          "list_samples", "set_thickness", "get_thickness"]:
            assert forbidden not in MICROSCOPE_API_SPEC, (
                f"simulation-only concept '{forbidden}' leaked into the "
                f"portable control spec"
            )

    def test_spec_mentions_units_and_limits(self):
        assert "METRES" in MICROSCOPE_API_SPEC
        assert "DEGREES" in MICROSCOPE_API_SPEC
        assert "1.5" in MICROSCOPE_API_SPEC  # x/y limit in mm
        assert "converged" in MICROSCOPE_API_SPEC

    def test_spec_mentions_haadf_detector(self):
        assert DEFAULT_DETECTOR in MICROSCOPE_API_SPEC


class TestWorkflowTemplates:
    def test_templates_is_dict(self):
        assert isinstance(WORKFLOW_TEMPLATES, dict)
        assert len(WORKFLOW_TEMPLATES) >= 4

    def test_expected_keys_present(self):
        for key in ["tilt_series", "diffraction_scan", "grid_scan",
                    "magnification_series"]:
            assert key in WORKFLOW_TEMPLATES

    def test_each_template_is_nonempty_string(self):
        for name, code in WORKFLOW_TEMPLATES.items():
            assert isinstance(code, str) and code.strip(), name

    def test_templates_use_control_client_only(self):
        for name, code in WORKFLOW_TEMPLATES.items():
            for forbidden in ["load_sample", "set_environment", "set_drift",
                              "set_specimen", "STEMClient", "SimulationHarness",
                              "set_thickness", "get_thickness"]:
                assert forbidden not in code, f"{name} uses {forbidden}"

    def test_spec_documents_new_control_surface(self):
        """The v6+ additions must be visible to the LLM."""
        for method in ["set_resolution", "get_resolution", "acquire_spectrum"]:
            assert f"mic.{method}(" in MICROSCOPE_API_SPEC, (
                f"{method} missing from the documented control surface"
            )
        assert "512" in MICROSCOPE_API_SPEC and "2048" in MICROSCOPE_API_SPEC
        assert "EELS" in MICROSCOPE_API_SPEC

    def test_acquiring_templates_report_images(self):
        for name, code in WORKFLOW_TEMPLATES.items():
            if "acquire_image" in code:
                assert "report_image(" in code, (
                    f"template '{name}' acquires but never reports the frame"
                )

    def test_templates_handle_failures(self):
        assert "except RuntimeError" in WORKFLOW_TEMPLATES["tilt_series"]
        assert 'af["converged"]' in WORKFLOW_TEMPLATES["grid_scan"]


class TestControlClientSource:
    def test_path_points_to_existing_file(self):
        assert CONTROL_CLIENT_SOURCE_PATH.exists()

    def test_source_contains_control_client_class(self):
        src = CONTROL_CLIENT_SOURCE_PATH.read_text()
        assert "class MicroscopeControlClient" in src
        assert "SimulationHarness" not in src


class TestImageMarker:
    def test_marker_is_distinctive(self):
        assert IMAGE_MARKER.startswith("##")
        assert len(IMAGE_MARKER) >= 10
