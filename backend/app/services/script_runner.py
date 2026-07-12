"""
Sandboxed execution of generated automation scripts.

The script that runs here is byte-for-byte the script a user would deploy on
a real instrument: it talks to the twin over the same MicroscopeControlClient
it embeds. The runner adds process isolation (subprocess in a temp dir),
a hard timeout, and a stdout marker protocol for streaming images back.

Marker protocol: the generated script prints one line per acquired frame:

    ##GRIDSCOPE_IMAGE##{"raw_b64": ..., "shape": [H, W], "dtype": "uint16",
                        "meta": {...}}

The runner decodes the raw frame and re-encodes it as displayable PNG base64.
All other stdout lines stream through as log events.
"""

import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, Generator

import numpy as np

from ..constants import IMAGE_MARKER
from .twin_session import encode_image_png_b64

DEFAULT_TIMEOUT_S = 300
MAX_LOG_LINE_CHARS = 4000          # plain log lines are truncated beyond this
MAX_MARKER_PAYLOAD_BYTES = 64_000_000  # refuse absurd frames
MAX_IMAGES_PER_RUN = 500


def _decode_image_line(line: str) -> Dict[str, Any]:
    payload = line[len(IMAGE_MARKER):]
    if len(payload) > MAX_MARKER_PAYLOAD_BYTES:
        raise ValueError("image payload exceeds size limit")
    obj = json.loads(payload)
    raw = base64.b64decode(obj["raw_b64"])
    arr = np.frombuffer(raw, dtype=np.dtype(obj["dtype"])).reshape(obj["shape"])
    return {"type": "image", "image": encode_image_png_b64(arr),
            "meta": obj.get("meta", {})}


def run_script(code: str, timeout_s: int = DEFAULT_TIMEOUT_S
               ) -> Generator[Dict[str, Any], None, None]:
    """Execute `code` in a subprocess, yielding event dicts:

    {"type": "log", "message": str}
    {"type": "image", "image": {...png b64...}, "meta": {...}}
    {"type": "error", "message": str}
    {"type": "done", "exit_code": int, "elapsed_s": float, "images": int}
    """
    started = time.time()
    n_images = 0
    with tempfile.TemporaryDirectory(prefix="gridscope_run_") as tmpdir:
        script_path = os.path.join(tmpdir, "script.py")
        with open(script_path, "w") as f:
            f.write(code)

        proc = subprocess.Popen(
            [sys.executable, "-u", script_path],
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own process group -> clean kill of children
        )

        # The timeout must fire even if the script goes silent: reading
        # proc.stdout blocks until a line arrives, so an in-loop deadline
        # check alone would hang forever on a quiet infinite loop. The timer
        # kills the process group out-of-band, which EOFs stdout and unblocks
        # the read loop.
        timed_out = threading.Event()

        def _on_timeout():
            timed_out.set()
            _kill_group(proc)

        timer = threading.Timer(timeout_s, _on_timeout)
        timer.start()
        budget_exceeded = False
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                if line.startswith(IMAGE_MARKER):
                    n_images += 1
                    if n_images > MAX_IMAGES_PER_RUN:
                        budget_exceeded = True
                        yield {"type": "error",
                               "message": f"Run exceeded {MAX_IMAGES_PER_RUN} images; stopping."}
                        _kill_group(proc)
                        break
                    try:
                        yield _decode_image_line(line)
                    except Exception as e:  # noqa: BLE001 — malformed marker is a script bug
                        yield {"type": "error",
                               "message": f"Malformed image marker from script: {e}"}
                else:
                    yield {"type": "log", "message": line[:MAX_LOG_LINE_CHARS]}
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                _kill_group(proc)
                proc.wait()
            stderr = ""
            if proc.stderr is not None:
                try:
                    stderr = proc.stderr.read() or ""
                except Exception:  # noqa: BLE001 — best-effort stderr drain
                    stderr = ""

        if timed_out.is_set():
            yield {"type": "error",
                   "message": f"Script exceeded the {timeout_s}s time limit and was stopped."}
        exit_code = proc.returncode if proc.returncode is not None else -1
        if exit_code != 0 and not timed_out.is_set() and not budget_exceeded \
                and stderr.strip():
            # Surface the tail of the traceback — that's what identifies the bug.
            tail = "\n".join(stderr.strip().splitlines()[-15:])
            yield {"type": "error", "message": tail}
        yield {"type": "done", "exit_code": exit_code,
               "elapsed_s": round(time.time() - started, 2), "images": n_images}


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
