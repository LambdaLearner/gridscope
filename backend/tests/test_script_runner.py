"""Failure-mode-first tests for the sandboxed script runner.

The runner's correctness is defined by its edge cases: timeouts (with child
cleanup), mid-run exceptions, malformed image markers, and oversized output.
One happy-path test anchors the contract.
"""

import base64
import json

import numpy as np
import pytest

from app.constants import IMAGE_MARKER
from app.services.script_runner import run_script


def events_of(code: str, timeout_s: int = 30):
    return list(run_script(code, timeout_s=timeout_s))


def types_of(events):
    return [e["type"] for e in events]


class TestHappyPath:
    def test_logs_images_and_done(self):
        img = np.arange(64, dtype=np.uint16).reshape(8, 8)
        payload = json.dumps({
            "raw_b64": base64.b64encode(img.tobytes()).decode(),
            "shape": [8, 8],
            "dtype": "uint16",
            "meta": {"label": "tile 0"},
        })
        code = (
            'print("starting")\n'
            f'print({(IMAGE_MARKER + payload)!r})\n'
            'print("done line")\n'
        )
        events = events_of(code)
        assert types_of(events) == ["log", "image", "log", "done"]
        assert events[0]["message"] == "starting"
        assert events[1]["meta"] == {"label": "tile 0"}
        assert events[1]["image"]["width"] == 8
        assert events[3]["exit_code"] == 0
        assert events[3]["images"] == 1


class TestFailureModes:
    def test_script_exception_surfaces_traceback_tail(self):
        events = events_of(
            'print("before crash")\n'
            'raise ValueError("intentional test failure")\n'
        )
        assert events[0] == {"type": "log", "message": "before crash"}
        error = next(e for e in events if e["type"] == "error")
        assert "intentional test failure" in error["message"]
        done = events[-1]
        assert done["type"] == "done"
        assert done["exit_code"] != 0

    def test_timeout_kills_the_process(self):
        events = events_of(
            'import time\n'
            'print("looping", flush=True)\n'
            'while True: time.sleep(0.1)\n',
            timeout_s=2,
        )
        error = next(e for e in events if e["type"] == "error")
        assert "time limit" in error["message"]
        assert events[-1]["type"] == "done"

    def test_malformed_image_marker_is_error_but_run_continues(self):
        code = (
            f'print("{IMAGE_MARKER}" + "this is not json")\n'
            'print("still alive")\n'
        )
        events = events_of(code)
        assert types_of(events) == ["error", "log", "done"]
        assert "Malformed image marker" in events[0]["message"]
        assert events[-1]["exit_code"] == 0

    def test_marker_with_bad_shape_is_error(self):
        payload = json.dumps({
            "raw_b64": base64.b64encode(b"\x00\x00").decode(),
            "shape": [100, 100],  # does not match 2 bytes
            "dtype": "uint16",
        })
        events = events_of(f'print({(IMAGE_MARKER + payload)!r})\n')
        assert events[0]["type"] == "error"

    def test_oversized_log_lines_truncated(self):
        events = events_of('print("x" * 100000)\n')
        log = events[0]
        assert log["type"] == "log"
        assert len(log["message"]) <= 4000

    def test_empty_script_completes(self):
        events = events_of("")
        assert events[-1]["type"] == "done"
        assert events[-1]["exit_code"] == 0

    def test_syntax_error_reported(self):
        events = events_of("def broken(:\n")
        error = next(e for e in events if e["type"] == "error")
        assert "SyntaxError" in error["message"]


class TestControlOnlyGuarantee:
    """The control-only property of generated scripts is enforced at
    generation time — verify the template and helpers uphold it."""

    def test_template_embeds_control_client_only(self):
        from app.models.schemas import CodeGenerationRequest
        from app.services.code_generator import MicroscopyCodeGenerator

        gen = MicroscopyCodeGenerator(api_key=None)
        code = gen.generate_from_template(
            CodeGenerationRequest(objective="grid scan")
        )
        assert "class MicroscopeControlClient" in code
        assert "SimulationHarness" not in code
        # No simulation-only commands anywhere in the generated script.
        for forbidden in ["load_sample", "set_environment", "set_drift",
                          "set_specimen", "reset_specimen"]:
            assert forbidden not in code, f"sim-only call in script: {forbidden}"

    def test_template_script_compiles(self):
        from app.models.schemas import CodeGenerationRequest
        from app.services.code_generator import MicroscopyCodeGenerator

        gen = MicroscopyCodeGenerator(api_key=None)
        code = gen.generate_from_template(
            CodeGenerationRequest(objective="grid scan")
        )
        compile(code, "<generated>", "exec")

    def test_template_reports_images(self):
        from app.models.schemas import CodeGenerationRequest
        from app.services.code_generator import MicroscopyCodeGenerator

        gen = MicroscopyCodeGenerator(api_key=None)
        code = gen.generate_from_template(
            CodeGenerationRequest(objective="grid scan")
        )
        assert "def report_image" in code
        assert IMAGE_MARKER in code
        assert "report_image(img" in code

    def test_ensure_self_contained_is_idempotent(self):
        from app.services.code_generator import ensure_self_contained

        once = ensure_self_contained("mic = MicroscopeControlClient()\n")
        twice = ensure_self_contained(once)
        assert once == twice
        assert once.count("class MicroscopeControlClient") == 1


class TestRunRoute:
    def test_run_endpoint_streams_and_respects_lock(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import twin_session as ts

        ts.end_run()
        client = TestClient(app)

        with client.stream("POST", "/api/execute/run",
                           json={"code": 'print("hello from sandbox")'}) as r:
            assert r.status_code == 200
            body = "".join(chunk for chunk in r.iter_text())
        assert "hello from sandbox" in body
        assert '"type": "done"' in body
        # Lock released after the stream ends.
        assert ts.run_status()["active"] is False

    def test_second_run_rejected_while_active(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import twin_session as ts

        ts.end_run()
        client = TestClient(app)
        assert ts.try_begin_run("occupier")
        try:
            r = client.post("/api/execute/run", json={"code": "print(1)"})
            assert r.status_code == 409
        finally:
            ts.end_run()

    def test_empty_script_is_400(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import twin_session as ts

        ts.end_run()
        client = TestClient(app)
        r = client.post("/api/execute/run", json={"code": "   "})
        assert r.status_code == 400


@pytest.mark.parametrize("n_over", [1])
def test_image_budget_enforced(monkeypatch, n_over):
    import app.services.script_runner as sr
    monkeypatch.setattr(sr, "MAX_IMAGES_PER_RUN", 2)

    img = np.zeros((2, 2), dtype=np.uint16)
    payload = json.dumps({
        "raw_b64": base64.b64encode(img.tobytes()).decode(),
        "shape": [2, 2], "dtype": "uint16",
    })
    line = f'print({(IMAGE_MARKER + payload)!r})\n'
    events = list(sr.run_script(line * (2 + n_over), timeout_s=30))
    error = next(e for e in events if e["type"] == "error")
    assert "images" in error["message"]
