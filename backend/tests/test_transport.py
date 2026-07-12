"""Netstring JSON-RPC transport smoke tests.

Starts the real Twisted server once (daemon thread, private port) and talks
to it through the real MicroscopeControlClient / SimulationHarness — the same
path the FastAPI backend and generated scripts use.
"""

import threading
import time

import numpy as np
import pytest

from app.digital_twin.control_client import MicroscopeControlClient
from app.digital_twin.sim_harness import SimulationHarness

PORT = 9195  # private test port; leaves 9094 free for a dev server


@pytest.fixture(scope="module")
def control():
    from twisted.internet import reactor, threads
    from app.digital_twin.server import STEMServer, NetstringFactory

    srv = STEMServer(D=16, H=96, W=96)
    reactor.callWhenRunning(
        lambda: reactor.listenTCP(PORT, NetstringFactory(srv), interface="127.0.0.1")
    )
    reactor.callWhenRunning(lambda: threads.deferToThread(srv.finish_init))
    t = threading.Thread(
        target=lambda: reactor.run(installSignalHandlers=False), daemon=True
    )
    t.start()

    client = MicroscopeControlClient(host="127.0.0.1", port=PORT, timeout=30)
    client.wait_until_ready(timeout=30)
    return client


class TestTransport:
    def test_ready_over_socket(self, control):
        r = control.is_ready()
        assert r["ready"] is True

    def test_register_and_acquire_over_socket(self, control):
        harness = SimulationHarness(control)
        r = harness.load_sample("fcc_single_crystal", D=16, H=96, W=96)
        assert r["loaded"] == "fcc_single_crystal"
        img = control.acquire_image("haadf")
        assert isinstance(img, np.ndarray)
        assert img.shape == (512, 512)
        assert img.dtype == np.uint16

    def test_limit_rejection_crosses_transport_as_error(self, control):
        with pytest.raises(RuntimeError, match="rejected by safety limits"):
            control.set_stage({"x": 2e-3}, relative=False)

    def test_connection_error_when_server_absent(self):
        client = MicroscopeControlClient(host="127.0.0.1", port=9999, timeout=2)
        with pytest.raises(OSError):
            client.is_ready()
