"""Tests for code_generator.py — embedded control client and script template."""

from app.constants import DEFAULT_DETECTOR
from app.models.schemas import CodeGenerationRequest, ExperimentConfig, GridConfig, StagePosition
from app.services.code_generator import (
    CONTROL_CLIENT_CODE,
    DIGITAL_TWIN_TEMPLATE,
    REPORT_IMAGE_HELPER,
    MicroscopyCodeGenerator,
    ensure_self_contained,
)


class TestEmbeddedControlClient:
    def test_code_is_nonempty(self):
        assert isinstance(CONTROL_CLIENT_CODE, str)
        assert len(CONTROL_CLIENT_CODE) > 200

    def test_code_contains_control_client_class(self):
        assert "class MicroscopeControlClient" in CONTROL_CLIENT_CODE

    def test_code_contains_control_methods(self):
        required = [
            "def is_ready",
            "def get_detectors",
            "def device_settings",
            "def get_stage",
            "def set_stage",
            "def get_stage_limits",
            "def get_magnification",
            "def set_magnification",
            "def get_beam",
            "def set_beam",
            "def get_mode",
            "def set_mode",
            "def acquire_image",
            "def autofocus",
        ]
        for method in required:
            assert method in CONTROL_CLIENT_CODE, f"Missing: {method}"

    def test_code_has_no_simulation_surface(self):
        for forbidden in ["SimulationHarness", "load_sample", "set_environment",
                          "set_drift", "set_specimen"]:
            assert forbidden not in CONTROL_CLIENT_CODE, f"Found: {forbidden}"

    def test_code_compiles(self):
        compile(CONTROL_CLIENT_CODE, "<control_client>", "exec")


class TestReportImageHelper:
    def test_helper_compiles(self):
        compile(REPORT_IMAGE_HELPER, "<report_image>", "exec")

    def test_helper_defines_report_image(self):
        assert "def report_image" in REPORT_IMAGE_HELPER


class TestGeneratedScript:
    def _generate(self, config=None):
        gen = MicroscopyCodeGenerator(api_key=None)
        return gen.generate_from_template(
            CodeGenerationRequest(objective="test objective",
                                  experiment_config=config)
        )

    def test_script_compiles(self):
        compile(self._generate(), "<script>", "exec")

    def test_script_uses_correct_detector(self):
        code = self._generate()
        assert "flu_camera" not in code
        assert DEFAULT_DETECTOR in code

    def test_script_checks_sample_registration(self):
        # A script run without a registered sample must fail clearly, not
        # image a nonexistent specimen.
        assert "No sample registered" in self._generate()

    def test_script_handles_stage_limit_rejections(self):
        assert "except RuntimeError" in self._generate()

    def test_script_handles_autofocus_nonconvergence(self):
        assert 'af["converged"]' in self._generate()

    def test_script_respects_experiment_config(self):
        config = ExperimentConfig(
            fov=12.5, voltage_kv=200, current_value=50,
            grid=GridConfig(rows=2, cols=3, overlap_percent=10, step_size=8.0),
            start_pos=StagePosition(x=1.0, y=2.0),
            dwell_s=0.1,
        )
        code = self._generate(config)
        assert '"grid_rows": 2' in code
        assert '"grid_cols": 3' in code
        assert '"field_of_view_um": 12.5' in code

    def test_template_has_no_simulation_calls(self):
        for forbidden in ["load_sample", "set_environment", "set_drift",
                          "set_specimen", "reset_specimen", "STEMClient"]:
            assert forbidden not in DIGITAL_TWIN_TEMPLATE, f"Found: {forbidden}"


class TestEnsureSelfContained:
    def test_prepends_client_when_missing(self):
        result = ensure_self_contained("mic.get_stage()")
        assert result.count("class MicroscopeControlClient") == 1
        assert "def report_image" in result

    def test_defines_mic_connection(self):
        # LLM output uses `mic` directly; the bootstrap must define it or the
        # script dies with NameError before its first command.
        result = ensure_self_contained('mic.set_stage({"x": 0}, relative=False)')
        assert 'mic = MicroscopeControlClient(' in result
        compile(result, "<generated>", "exec")

    def test_idempotent(self):
        once = ensure_self_contained("x = 1")
        assert ensure_self_contained(once) == once


class TestReportImageStageInjection:
    """The helper reads the stage back from the client and attaches the
    authoritative position to every frame (v3 fix for 'position shown is not
    correct while running LLM code')."""

    class FakeMic:
        def get_stage(self):
            # metres / degrees, as the real client returns
            return [2.5e-6, -1.25e-6, 0.5e-6, 3.0, -7.5]

    def _run_helper(self, capsys, script_tail):
        import json as _json

        from app.constants import IMAGE_MARKER

        ns = {}
        exec(REPORT_IMAGE_HELPER, ns)
        ns["FakeMic"] = self.FakeMic
        exec(script_tail, ns)
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if l.startswith(IMAGE_MARKER))
        return _json.loads(line[len(IMAGE_MARKER):])

    def test_stage_attached_from_explicit_mic(self, capsys):
        import numpy as np
        payload = self._run_helper(capsys, (
            "import numpy as np\n"
            "report_image(np.zeros((4, 4), dtype='uint16'), FakeMic(), label='t')\n"
        ))
        meta = payload["meta"]
        assert meta["x_um"] == 2.5
        assert meta["y_um"] == -1.25
        assert meta["z_um"] == 0.5
        assert meta["a_deg"] == 3.0
        assert meta["b_deg"] == -7.5
        assert meta["stage"]["x_um"] == 2.5
        assert meta["label"] == "t"

    def test_stage_attached_from_module_level_mic(self, capsys):
        payload = self._run_helper(capsys, (
            "import numpy as np\n"
            "mic = FakeMic()\n"
            "report_image(np.zeros((4, 4), dtype='uint16'))\n"
        ))
        assert payload["meta"]["x_um"] == 2.5

    def test_explicit_meta_wins_over_readback(self, capsys):
        payload = self._run_helper(capsys, (
            "import numpy as np\n"
            "report_image(np.zeros((4, 4), dtype='uint16'), FakeMic(), x_um=99.0)\n"
        ))
        assert payload["meta"]["x_um"] == 99.0     # script-supplied wins
        assert payload["meta"]["y_um"] == -1.25    # rest still attached

    def test_no_mic_in_scope_still_reports(self, capsys):
        payload = self._run_helper(capsys, (
            "import numpy as np\n"
            "report_image(np.zeros((4, 4), dtype='uint16'), label='bare')\n"
        ))
        assert payload["meta"] == {"label": "bare"}

    def test_broken_get_stage_never_fails_the_report(self, capsys):
        payload = self._run_helper(capsys, (
            "import numpy as np\n"
            "class Broken:\n"
            "    def get_stage(self):\n"
            "        raise RuntimeError('link down')\n"
            "report_image(np.zeros((4, 4), dtype='uint16'), Broken(), label='x')\n"
        ))
        assert payload["meta"] == {"label": "x"}

    def test_template_passes_mic_to_report_image(self):
        gen = MicroscopyCodeGenerator(api_key=None)
        code = gen.generate_from_template(
            CodeGenerationRequest(objective="grid scan"))
        assert "report_image(img, mic" in code
