"""
sim_harness.py — twin-only test-harness configuration.

NONE of these methods has a real-instrument counterpart: they choose the
specimen and inject acquisition conditions (drift, contamination, detector
noise). A real deployment has no SimulationHarness. Generated automation
scripts must never use this class.
"""


class SimulationHarness:
    """Twin-only configuration: choose the specimen and inject acquisition
    conditions (drift / contamination / noise). A real deployment has no
    equivalent.

    Wraps a MicroscopeControlClient and reuses its connection for the twin's
    simulation commands. Access the control surface via `.control`."""

    def __init__(self, control_client):
        self.control = control_client

    def _call(self, method, params=None):
        # Simulation RPCs travel over the control client's transport: in the twin,
        # control and simulation commands reach the same server process.
        return self.control._call(method, params)

    # ---- specimen selection (real microscopes have a physical specimen) ----
    def list_samples(self): return self._call("list_samples")
    def get_current_sample(self): return self._call("get_current_sample")
    def load_sample(self, name, params=None, D=None, H=None, W=None,
                    thickness_nm=None, thickness_seed=None):
        p = {"name": name, "params": params or {}}
        if D is not None: p["D"] = D
        if H is not None: p["H"] = H
        if W is not None: p["W"] = W
        if thickness_nm is not None: p["thickness_nm"] = thickness_nm
        if thickness_seed is not None: p["thickness_seed"] = thickness_seed
        return self._call("load_sample", p)

    # ---- specimen thickness selection (twin-only: on a real instrument the
    # local thickness is whatever region of the physical foil you are on) ----
    def get_thickness(self): return self._call("get_thickness")
    def set_thickness(self, thickness_nm=None, thickness_seed=None):
        p = {}
        if thickness_nm is not None: p["thickness_nm"] = thickness_nm
        if thickness_seed is not None: p["thickness_seed"] = thickness_seed
        return self._call("set_thickness", p)

    # ---- specimen degradation (contamination) ----
    def get_specimen(self): return self._call("get_specimen")
    def reset_specimen(self): return self._call("reset_specimen")

    # Contamination: carbon accumulating where the beam dwells. `rate` is a
    # percentage knob -- 100 is the calibrated nominal rate, 0 is off.
    def set_contamination(self, enabled=None, rate=None):
        p = {}
        if enabled is not None: p["enabled"] = enabled
        if rate is not None: p["rate"] = rate
        return self._call("set_contamination", p)

    # ---- detector / dose noise (everything governing how noisy a frame is) ----
    def set_noise(self, dwell_us=None, dqe=None, readout_e=None,
                  use_dose_model=None, noise_sigma=None, device="haadf"):
        p = {"device": device}
        for k, v in (("dwell_us", dwell_us), ("dqe", dqe), ("readout_e", readout_e),
                     ("use_dose_model", use_dose_model), ("noise_sigma", noise_sigma)):
            if v is not None: p[k] = v
        return self._call("set_noise", p)

    # ---- mechanical drift injection ----
    def get_drift(self): return self._call("get_drift")
    def set_drift(self, **kw): return self._call("set_drift", kw)

    # ---- twin introspection / debugging ----
    def get_command_log(self, last_n=50): return self._call("get_command_log", {"last_n": last_n})
    def clear_command_log(self): return self._call("clear_command_log")
