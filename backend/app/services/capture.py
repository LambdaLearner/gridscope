"""Efficient on-demand image capture (spec addendum A3, adapted from the
notebook's twin_io.TwinImageIO for a web GUI).

Design goals (per the "don't slow the system down" requirement):
  * NO growing in-memory gallery. We keep only the SINGLE most-recent
    acquisition (one float32 array). Saving is an explicit, on-demand action.
    Memory stays O(1 frame).
  * 32-bit float TIFF output — HAADF/DIFF frames keep their quantitative
    range (what you'd want from a real detector).
  * Sane names without timestamp clutter: a short, readable auto-name built
    from the acquisition context (mode, sample, mag, resolution).

Web adaptation: instead of writing into a server-side captures/ directory
(the notebook GUI shares a filesystem with its user; a browser does not),
the TIFF is built in memory and streamed as a download — the browser's own
download manager handles collisions, so the disk-dedup suffix logic is not
needed here. The acquisition context is embedded in the TIFF description
(ImageJ-readable JSON), so a saved file is self-describing.
"""

import io
import json
import re
import threading
from typing import Any, Dict, Optional, Tuple

import numpy as np

try:
    import tifffile

    _HAVE_TIFF = True
except Exception:  # pragma: no cover — exercised via the fallback test
    _HAVE_TIFF = False


class CaptureStore:
    """Single most-recent frame + its acquisition context."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last: Optional[np.ndarray] = None
        self._last_meta: Dict[str, Any] = {}

    def stash(self, image, meta: Optional[Dict[str, Any]] = None) -> None:
        """Store the latest frame (cheap; overwrites the previous one)."""
        arr = np.asarray(image).astype(np.float32, copy=False)
        with self._lock:
            self._last = arr
            self._last_meta = dict(meta or {})

    def has_image(self) -> bool:
        with self._lock:
            return self._last is not None

    def meta(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._last_meta)

    def clear(self) -> None:
        with self._lock:
            self._last = None
            self._last_meta = {}

    # -- short, readable name from context (same scheme as twin_io) --
    @staticmethod
    def auto_name(meta: Dict[str, Any]) -> str:
        parts = []
        m = meta.get("mode")
        if m:
            parts.append(str(m).lower())
        s = meta.get("sample")
        if s:  # shorten e.g. fcc_single_crystal -> fcc
            parts.append(re.sub(r"_.*$", "", str(s)))
        if meta.get("engine"):
            parts.append(str(meta["engine"]).lower())
        if meta.get("mag_kx"):
            parts.append(f"{int(round(float(meta['mag_kx'])))}kx")
        if meta.get("resolution"):
            parts.append(f"{int(meta['resolution'])}px")
        base = "_".join(p for p in parts if p) or "capture"
        return re.sub(r"[^A-Za-z0-9_.-]", "", base)

    def build_tiff(self, name: Optional[str] = None) -> Tuple[bytes, str, str]:
        """Build the stashed frame as 32-bit float TIFF bytes.

        Returns (payload, filename, media_type). Falls back to .npy bytes if
        tifffile is unavailable. Raises RuntimeError if nothing is stashed.
        """
        with self._lock:
            if self._last is None:
                raise RuntimeError("No image to save yet (acquire one first).")
            img32 = self._last
            meta = dict(self._last_meta)
        base = re.sub(r"\.tif+$", "", name, flags=re.I) if name else self.auto_name(meta)
        base = re.sub(r"[^A-Za-z0-9_.-]", "", base) or "capture"
        buf = io.BytesIO()
        if _HAVE_TIFF:
            tifffile.imwrite(buf, img32, description=json.dumps(meta),
                             metadata=meta, dtype=np.float32)
            return buf.getvalue(), f"{base}.tif", "image/tiff"
        np.save(buf, img32)  # dependency-free fallback
        return buf.getvalue(), f"{base}.npy", "application/octet-stream"


# One store for the app: "the current view" is a single global concept, like
# the single most-recent frame on a real acquisition PC.
store = CaptureStore()
