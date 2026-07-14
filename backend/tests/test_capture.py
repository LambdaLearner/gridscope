"""Tests for the on-demand 32-bit TIFF capture path (spec addendum A3/A4):
O(1) stash, context-derived filenames, embedded metadata, HTTP download."""

import io as _io
import json

import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient

from app.main import app
from app.services.capture import CaptureStore, store


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()
    yield
    store.clear()


class TestCaptureStore:
    def test_stash_keeps_only_latest_frame(self):
        s = CaptureStore()
        s.stash(np.ones((4, 4), dtype=np.uint16), meta={"mode": "IMG"})
        s.stash(np.full((8, 8), 7, dtype=np.uint16), meta={"mode": "DIFF"})
        payload, filename, _ = s.build_tiff()
        assert s.meta()["mode"] == "DIFF"
        assert filename.startswith("diff")
        arr = tifffile.imread(_io.BytesIO(payload))
        assert arr.shape == (8, 8)
        assert arr.dtype == np.float32

    def test_auto_name_from_context(self):
        name = CaptureStore.auto_name({
            "mode": "DIFF", "sample": "fcc_single_crystal",
            "mag_kx": 2000.4, "resolution": 1024,
        })
        assert name == "diff_fcc_2000kx_1024px"

    def test_auto_name_tags_abtem_engine(self):
        name = CaptureStore.auto_name({
            "mode": "DIFF", "sample": "fcc_single_crystal", "engine": "abTEM",
        })
        assert "abtem" in name

    def test_auto_name_sanitizes_and_falls_back(self):
        assert CaptureStore.auto_name({}) == "capture"
        assert "/" not in CaptureStore.auto_name({"sample": "../evil"})

    def test_metadata_embedded_in_tiff_description(self):
        s = CaptureStore()
        meta = {"mode": "IMG", "sample": "au_dispersed", "voltage_kV": 200.0}
        s.stash(np.zeros((4, 4)), meta=meta)
        payload, _, _ = s.build_tiff()
        with tifffile.TiffFile(_io.BytesIO(payload)) as tf:
            desc = tf.pages[0].description
        assert "au_dispersed" in desc

    def test_build_without_stash_raises(self):
        with pytest.raises(RuntimeError, match="No image"):
            CaptureStore().build_tiff()

    def test_explicit_name_overrides_and_is_sanitized(self):
        s = CaptureStore()
        s.stash(np.zeros((2, 2)))
        _, filename, _ = s.build_tiff(name="my pattern!.tif")
        assert filename == "mypattern.tif"

    def test_stash_is_float32(self):
        s = CaptureStore()
        s.stash(np.array([[1, 2]], dtype=np.uint16))
        payload, _, _ = s.build_tiff()
        assert tifffile.imread(_io.BytesIO(payload)).dtype == np.float32


class TestCaptureRoutes:
    def test_capture_info_empty(self):
        r = TestClient(app).get("/api/microscope/capture")
        assert r.status_code == 200
        assert r.json() == {"has_image": False}

    def test_download_without_capture_is_404(self):
        r = TestClient(app).get("/api/microscope/capture.tiff")
        assert r.status_code == 404
        assert "No image" in r.json()["detail"]

    def test_download_streams_tiff_with_filename(self):
        store.stash(np.ones((16, 16), dtype=np.uint16),
                    meta={"mode": "DIFF", "sample": "fcc_single_crystal",
                          "engine": "kinematical", "mag_kx": 57, "resolution": 512})
        client = TestClient(app)
        info = client.get("/api/microscope/capture").json()
        assert info["has_image"] is True
        assert info["filename"] == "diff_fcc_kinematical_57kx_512px.tif"
        r = client.get("/api/microscope/capture.tiff")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/tiff"
        assert "attachment" in r.headers["content-disposition"]
        arr = tifffile.imread(_io.BytesIO(r.content))
        assert arr.shape == (16, 16)
        assert arr.dtype == np.float32

    def test_download_with_custom_name(self):
        store.stash(np.zeros((4, 4)))
        r = TestClient(app).get("/api/microscope/capture.tiff?name=my_pattern")
        assert 'filename="my_pattern.tif"' in r.headers["content-disposition"]
