#!/usr/bin/env python3
"""Ground-truth validation of ablation scripts against the digital twin.

The temperature ablation (scripts/temperature_ablation.py) characterises each
generated plan STATICALLY (AST loop unrolling). This script validates those
estimates dynamically: it executes selected generated scripts from
ablation/results.jsonl against the real digital twin — through the exact
production path (app.services.script_runner sandbox, netstring JSON-RPC to a
Twisted STEMServer on 127.0.0.1:9094, the port the generated bootstrap
hardcodes) — and reads the twin's server-side command log to count how many
`acquire_image` calls actually completed.

Per run, the twin is reset to a pristine state, the prompt-appropriate sample
is registered through SimulationHarness.load_sample (FCC single crystal for
prompt 1, dispersed Au nanoparticles for prompts 2-4 — scripts refuse to image
without a registered sample), and the command log is cleared so counts reflect
the script alone. Ground truth is the server-side log; stdout-reported images
(##GRIDSCOPE_IMAGE## markers) are recorded as a cross-check. Scripts that fail
or time out keep their partial counts — the log records completed commands.

Twin lifecycle: a Twisted listener is started in-process and a brand-new
STEMServer instance is swapped in before every script (perfect isolation).
If port 9094 is free the scripts run byte-for-byte. If a dev twin already
occupies 9094 (its log would be polluted by the live GUI's own acquisitions),
the private listener binds a free port instead and the ONE bootstrap line
`mic = MicroscopeControlClient(host="127.0.0.1", port=9094)` is retargeted to
it; the LLM-authored workflow code is never modified.

Usage (from backend/):
    venv/bin/python scripts/validate_ablation_counts.py                # manuscript validation set
    venv/bin/python scripts/validate_ablation_counts.py --keys 1:0.0:1 2:0.7:10
    venv/bin/python scripts/validate_ablation_counts.py --timeout 300

Writes a markdown report to ablation/validation.md (and raw records to
ablation/validation.jsonl) and prints the table to stdout.
"""

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from app.digital_twin.control_client import MicroscopeControlClient
from app.digital_twin.sim_harness import SimulationHarness
from app.services import script_runner
from temperature_ablation import extract_features, strip_boilerplate

TWIN_HOST = "127.0.0.1"
TWIN_PORT = 9094              # generated scripts hardcode this port
FALLBACK_PORT = 9196          # private port when a dev twin occupies 9094
BOOTSTRAP_LINE = 'mic = MicroscopeControlClient(host="127.0.0.1", port=9094)'
DEFAULT_TIMEOUT_S = 600       # hard cap per script; partial counts survive
COMMAND_LOG_LIMIT = 1_000_000

# Which sample each prompt's script expects to find registered.
SAMPLE_FOR_PROMPT = {
    1: "fcc_single_crystal",  # "Using the FCC sample, ..."
    2: "au_dispersed",        # "Using the Au nanoparticle sample, ..."
    3: "au_dispersed",        # "On the Au sample, ..."
    4: "au_dispersed",        # "... on the Au sample ..."
}

# Manuscript validation set: (prompt_id, temperature, run).
DEFAULT_KEYS = [
    (1, 0.0, 1), (2, 0.0, 1), (3, 0.0, 1), (3, 0.0, 2), (4, 0.0, 1),
    (4, 0.0, 18), (2, 0.7, 1), (2, 0.7, 10), (4, 0.3, 9), (4, 0.7, 14),
    (3, 0.7, 16), (4, 0.3, 1),
]


# ---------------------------------------------------------------------------
# Twin server lifecycle
# ---------------------------------------------------------------------------

def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def start_twin_listener(port: int):
    """Start the Twisted netstring listener once; the factory's server
    instance is swapped per validated script for full state isolation."""
    from twisted.internet import reactor
    from app.digital_twin.server import NetstringFactory, STEMServer

    factory = NetstringFactory(None)  # server swapped in before first use
    reactor.callWhenRunning(
        lambda: reactor.listenTCP(port, factory, interface=TWIN_HOST)
    )
    thread = threading.Thread(
        target=lambda: reactor.run(installSignalHandlers=False), daemon=True
    )
    thread.start()

    def fresh_server() -> None:
        srv = STEMServer()          # product defaults (D=64, H=768, W=768)
        srv.finish_init()           # sample discovery; no sample preloaded
        factory.server_instance = srv

    return fresh_server


def make_twin_preparer():
    """Return (prepare, port, mode) where prepare(sample_name) hands back a
    SimulationHarness on a pristine twin with the sample registered and the
    command log cleared.

    A private in-process twin is always used: a shared dev twin cannot serve
    as ground truth because the live GUI's own acquisitions land in the same
    command log. When 9094 is taken, scripts are retargeted to the fallback
    port (bootstrap connection line only)."""
    if not _port_in_use(TWIN_HOST, TWIN_PORT):
        port = TWIN_PORT
        mode = f"in-process twin on {TWIN_PORT}; scripts byte-for-byte"
    elif not _port_in_use(TWIN_HOST, FALLBACK_PORT):
        port = FALLBACK_PORT
        mode = (f"in-process twin on {FALLBACK_PORT} (9094 occupied by a dev "
                f"twin); script bootstrap line retargeted to {FALLBACK_PORT}")
    else:
        sys.exit(f"Ports {TWIN_PORT} and {FALLBACK_PORT} are both in use; "
                 f"free one and retry.")

    fresh_server = start_twin_listener(port)

    def prepare(sample_name: str) -> SimulationHarness:
        fresh_server()
        client = MicroscopeControlClient(host=TWIN_HOST, port=port, timeout=60)
        client.wait_until_ready(timeout=120)
        harness = SimulationHarness(client)
        harness.load_sample(sample_name)
        harness.clear_command_log()
        return harness

    return prepare, port, mode


def retarget_script(code: str, port: int) -> str:
    """Point the script's connection bootstrap at `port`. Only the prepended
    bootstrap line changes; the LLM-authored workflow code is untouched."""
    if port == TWIN_PORT:
        return code
    if BOOTSTRAP_LINE not in code:
        raise ValueError("script lacks the standard connection bootstrap; "
                         "cannot retarget it to the validation twin")
    return code.replace(
        BOOTSTRAP_LINE, BOOTSTRAP_LINE.replace("port=9094", f"port={port}"))


# ---------------------------------------------------------------------------
# Per-script execution
# ---------------------------------------------------------------------------

def load_records(results_path: Path) -> dict:
    """Latest record per (prompt_id, temperature, run) — mirrors the ablation
    report's resume semantics."""
    records = {}
    for line in results_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        records[(rec["prompt_id"], rec["temperature"], rec["run"])] = rec
    return records


def static_estimate(code: str) -> str:
    """Static acquisition estimate via the ablation study's own AST analysis."""
    features = extract_features(strip_boilerplate(code))
    if features["parse_error"]:
        return "unparseable"
    return (f"{features['est_acquisitions']}"
            f"{'+' if features['has_nonliteral_loops'] else ''}")


def validate_one(key: tuple, record: dict, prepare_twin, twin_port: int,
                 timeout_s: int) -> dict:
    prompt_id, temperature, run = key
    result = {
        "prompt_id": prompt_id, "temperature": temperature, "run": run,
        "sample": SAMPLE_FOR_PROMPT[prompt_id],
        "static_est_acq": None, "actual_acq": None, "reported_images": None,
        "set_stage_calls": None, "stage_rejections": None,
        "set_mode_calls": None, "exit_code": None, "elapsed_s": None,
        "error": None,
    }
    code = record.get("generated_code")
    if not code:
        result["error"] = "record has no generated_code"
        return result
    result["static_est_acq"] = static_estimate(code)
    try:
        code = retarget_script(code, twin_port)
    except ValueError as exc:
        result["error"] = str(exc)
        return result

    # Pristine twin + registered sample, through the same client/harness the
    # backend routes use. The command log is cleared inside prepare_twin, so
    # counts reflect the script alone.
    harness = prepare_twin(SAMPLE_FOR_PROMPT[prompt_id])

    errors = []
    reported = 0
    for event in script_runner.run_script(code, timeout_s=timeout_s):
        if event["type"] == "image":
            reported += 1
        elif event["type"] == "error":
            errors.append(event["message"])
        elif event["type"] == "done":
            result["exit_code"] = event["exit_code"]
            result["elapsed_s"] = event["elapsed_s"]

    time.sleep(1.0)  # let any RPC in flight at kill time land in the log
    log = harness.get_command_log(last_n=COMMAND_LOG_LIMIT)
    result["actual_acq"] = sum(1 for e in log if e["method"] == "acquire_image")
    stage_entries = [e for e in log if e["method"] == "set_stage"]
    result["set_stage_calls"] = len(stage_entries)
    result["stage_rejections"] = sum(
        1 for e in stage_entries if "rejected" in e.get("result_preview", ""))
    result["set_mode_calls"] = sum(1 for e in log if e["method"] == "set_mode")
    result["reported_images"] = reported
    if errors:
        result["error"] = " | ".join(errors)
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def build_table(results: list) -> str:
    lines = [
        "| Prompt | T | Run | Sample | Static est. acq | Actual acq (twin log) "
        "| Reported images (stdout) | set_stage | Stage rejections | set_mode "
        "| Exit | Time (s) | Runtime error |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        error = _md_escape(r["error"][:200]) if r["error"] else "—"
        lines.append(
            f"| P{r['prompt_id']} | {r['temperature']} | {r['run']} "
            f"| {r['sample']} | {r['static_est_acq']} | **{r['actual_acq']}** "
            f"| {r['reported_images']} | {r['set_stage_calls']} "
            f"| {r['stage_rejections']} | {r['set_mode_calls']} "
            f"| {r['exit_code']} | {r['elapsed_s']} | {error} |"
        )
    return "\n".join(lines)


def write_report(results: list, out_md: Path, timeout_s: int,
                 twin_mode: str) -> str:
    table = build_table(results)
    report = "\n".join([
        "# Ground-truth validation of ablation scripts",
        "",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- Method: each generated script from ablation/results.jsonl runs "
        "unmodified in the production sandbox (app.services.script_runner) "
        "against a real digital twin (Twisted STEMServer, netstring "
        "JSON-RPC). Before each run the twin is reset to a pristine state "
        "(fresh STEMServer instance) and the prompt's sample is registered via "
        "SimulationHarness.load_sample (fcc_single_crystal for P1, "
        "au_dispersed for P2-P4).",
        f"- Twin mode: {twin_mode}.",
        "- 'Actual acq' counts completed `acquire_image` entries in the twin's "
        "server-side command log (cleared after sample registration); "
        "'Reported images' counts ##GRIDSCOPE_IMAGE## markers the script "
        "emitted on stdout.",
        f"- Per-script timeout: {timeout_s} s; timed-out or failed scripts "
        "keep their partial counts.",
        "",
        table,
        "",
    ])
    out_md.write_text(report, encoding="utf-8")
    return table


# ---------------------------------------------------------------------------

def parse_key(text: str) -> tuple:
    try:
        pid, temp, run = text.split(":")
        return (int(pid), float(temp), int(run))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"bad key '{text}' (expected prompt_id:temperature:run, "
            f"e.g. 2:0.7:10)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keys", type=parse_key, nargs="+",
                        metavar="PID:T:RUN",
                        help="runs to validate (default: manuscript set)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                        help="per-script wall-clock cap in seconds")
    parser.add_argument("--results", type=Path,
                        default=BACKEND_ROOT / "ablation" / "results.jsonl")
    parser.add_argument("--out", type=Path,
                        default=BACKEND_ROOT / "ablation" / "validation.md")
    args = parser.parse_args()
    keys = args.keys or DEFAULT_KEYS

    records = load_records(args.results)
    prepare_twin, twin_port, twin_mode = make_twin_preparer()
    print(f"[validate] twin mode: {twin_mode}", flush=True)

    results = []
    jsonl_path = args.out.with_suffix(".jsonl")
    jsonl_path.write_text("", encoding="utf-8")
    for key in keys:
        pid, temp, run = key
        print(f"[validate] P{pid} T={temp} run {run} ...", flush=True)
        record = records.get(key)
        if record is None:
            result = {"prompt_id": pid, "temperature": temp, "run": run,
                      "sample": SAMPLE_FOR_PROMPT.get(pid, "?"),
                      "static_est_acq": None, "actual_acq": None,
                      "reported_images": None, "set_stage_calls": None,
                      "stage_rejections": None, "set_mode_calls": None,
                      "exit_code": None, "elapsed_s": None,
                      "error": "no such record in results.jsonl"}
        else:
            result = validate_one(key, record, prepare_twin, twin_port,
                                  args.timeout)
        results.append(result)
        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result) + "\n")
        print(f"[validate]   -> actual={result['actual_acq']} "
              f"reported={result['reported_images']} "
              f"static={result['static_est_acq']} "
              f"error={'yes' if result['error'] else 'no'}", flush=True)

    table = write_report(results, args.out, args.timeout, twin_mode)
    print()
    print(table)
    print(f"\nReport written to {args.out}")


if __name__ == "__main__":
    main()
