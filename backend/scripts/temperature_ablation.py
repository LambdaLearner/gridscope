#!/usr/bin/env python3
"""Temperature ablation study for the GridScope manuscript revision.

Runs the four manuscript prompts (Tables 1-4) N times at each temperature and
reports the full distribution of generated plans, answering the reviewer's
question of whether plan variability (e.g. 2x2 vs 3x3 grid choice) is a
sampling artefact or intrinsic prompt underspecification.

Faithfulness to the UI: each run calls the real /api/chat FastAPI handler
(app.routes.chat.chat) with exactly the payload AIAssistant.tsx sends — the
assistant greeting followed by a single user prompt, experiment_config=None
(App.tsx passes null) and context=None — so the system prompt, code-block
extraction, and ensure_self_contained wrapping are identical to production.
Each run is an independent fresh conversation.

Usage (from backend/):
    venv/bin/python scripts/temperature_ablation.py                # full study
    venv/bin/python scripts/temperature_ablation.py --runs 1 --temperatures 0 --prompts 4   # smoke test
    venv/bin/python scripts/temperature_ablation.py --report-only  # rebuild results.md

Raw per-run records append to <out>/results.jsonl (crash-safe; re-running
skips completed runs and retries failed ones). The report step writes
<out>/results.md with summary tables, per-prompt distributions,
manuscript-style step tables, and a full per-run appendix. The LLM audit log
for the study is kept at <out>/llm_calls.jsonl.
"""

import argparse
import ast
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

MAX_RETRIES = 5
DEFAULT_RUNS = 20
DEFAULT_TEMPERATURES = [0.0, 0.3, 0.7]
DEFAULT_CONCURRENCY = 4

# Verbatim copy of INITIAL_MESSAGE.content in src/components/AIAssistant.tsx —
# the chat history the UI sends always starts with this assistant greeting.
UI_GREETING = (
    "Hello! I'm your **STEM Digital Twin** assistant. I can help you:\n\n"
    "- **Control the microscope** - stage moves (within safety limits), "
    "imaging/diffraction modes, magnification\n"
    "- **Design experiments** - grid scans, tilt series, dose studies on the "
    "registered sample\n"
    "- **Generate portable Python scripts** - the same code runs on a real "
    "instrument\n\n"
    "Register a sample in **Sample Settings** first, then tell me what to do!"
)

# Revised manuscript prompts (LaTeX \rev{} text adopted, \st{} text dropped).
PROMPTS = {
    1: (
        "Using the FCC sample, generate a script that alternates between "
        "real-space imaging and diffraction mode at each tilt condition. For "
        "tilt values (α,β) = (0°,0°), (20°,18°), and (28°,25°), first acquire "
        "a real-space image, then switch to diffraction mode and acquire a "
        "diffraction image. Ensure that all acquisition parameters remain "
        "consistent across tilts and modes. Display outputs along with the "
        "corresponding tilt values."
    ),
    2: (
        "Using the Au nanoparticle sample, generate a microscope-control "
        "script to perform a hierarchical scan centered at the current stage "
        "position.\n"
        "First, acquire a coarse 3×3 grid of images in imaging mode using a "
        "field of view of 7 µm with 20% overlap between adjacent positions.\n"
        "Then, for each coarse grid position, acquire a higher-resolution "
        "image at the same stage location using a reduced field of view of "
        "2.5 µm while keeping all other imaging parameters consistent.\n"
        "Ensure that:\n"
        "- stage coordinates are computed correctly for the specified "
        "overlap,\n"
        "- stage positions are identical between the coarse and corresponding "
        "fine acquisitions,\n"
        "- the acquisition order preserves the hierarchical structure (coarse "
        "scan followed by fine scans at each location).\n"
        "Display all acquired images along with their stage position and tilt "
        "metadata."
    ),
    3: (
        "On the Au sample, perform a coarse-to-fine imaging workflow. Start "
        "by scanning the area around the current position using a small grid "
        "at low magnification, and then revisit each location to capture a "
        "more detailed image at higher magnification. Acquire all images.\n"
        "Ensure that the same stage positions are used for both scans and "
        "that the higher-resolution images correspond directly to the "
        "locations identified in the coarse scan. Maintain consistent imaging "
        "conditions across all acquisitions."
    ),
    4: (
        "Take an overview of the current region on the Au sample and then "
        "zoom in on each part of that overview to collect more detailed "
        "images. The detailed images should correspond to the same locations "
        "covered in the overview scan."
    ),
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_key(record: dict) -> tuple:
    return (record["prompt_id"], record["temperature"], record["run"])


def _load_completed(jsonl_path: Path) -> set:
    """Keys of runs that already succeeded (errors are retried on resume)."""
    completed = set()
    if not jsonl_path.exists():
        return completed
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not record.get("error"):
            completed.add(_run_key(record))
    return completed


async def _run_one(prompt_id: int, temperature: float, run_idx: int,
                   semaphore: asyncio.Semaphore, write_lock: asyncio.Lock,
                   jsonl_path: Path) -> None:
    from fastapi import HTTPException

    from app.models.schemas import ChatMessage, ChatRequest
    from app.routes.chat import chat as chat_endpoint

    request = ChatRequest(
        messages=[
            ChatMessage(role="assistant", content=UI_GREETING),
            ChatMessage(role="user", content=PROMPTS[prompt_id]),
        ],
        experiment_config=None,
        context=None,
    )

    record = {
        "prompt_id": prompt_id,
        "temperature": temperature,
        "run": run_idx,
        "timestamp": None,
        "message": None,
        "generated_code": None,
        "error": None,
        "attempts": 0,
    }

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            record["attempts"] = attempt
            try:
                response = await chat_endpoint(request)
                record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                record["message"] = response.message
                record["generated_code"] = response.generated_code
                record["error"] = None
                break
            except HTTPException as exc:
                record["error"] = f"HTTP {exc.status_code}: {exc.detail}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(min(60, 2 ** attempt * 2))

    async with write_lock:
        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    status = "ok" if not record["error"] else f"FAILED ({record['error'][:60]})"
    code = "code" if record["generated_code"] else "NO CODE BLOCK"
    print(f"  P{prompt_id} T={temperature} run {run_idx:2d}: {status} [{code}]")


async def run_study(runs: int, temperatures: list, prompt_ids: list,
                    concurrency: int, out_dir: Path) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set (expected in backend/.env)")

    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "results.jsonl"
    # Keep this study's LLM audit log alongside its results.
    os.environ["GRIDSCOPE_LLM_LOG"] = str(out_dir / "llm_calls.jsonl")

    completed = _load_completed(jsonl_path)
    if completed:
        print(f"Resuming: {len(completed)} completed runs will be skipped.")

    write_lock = asyncio.Lock()
    total_new = 0
    # Temperature groups run sequentially: the chat endpoint constructs its
    # agent per request from OPENAI_TEMPERATURE, so the env var must be
    # stable while a group's tasks are in flight.
    for temperature in temperatures:
        os.environ["OPENAI_TEMPERATURE"] = str(temperature)
        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            _run_one(pid, temperature, run_idx, semaphore, write_lock, jsonl_path)
            for pid in prompt_ids
            for run_idx in range(1, runs + 1)
            if (pid, temperature, run_idx) not in completed
        ]
        if not tasks:
            print(f"T={temperature}: nothing to do (all runs completed).")
            continue
        print(f"T={temperature}: launching {len(tasks)} runs "
              f"(concurrency {concurrency})...")
        total_new += len(tasks)
        await asyncio.gather(*tasks)

    print(f"Done: {total_new} new runs recorded in {jsonl_path}")


# ---------------------------------------------------------------------------
# Plan analysis
# ---------------------------------------------------------------------------

def strip_boilerplate(code: str) -> str:
    """Return only the LLM-authored part of an ensure_self_contained script."""
    from app.services.code_generator import (
        CONNECTION_BOOTSTRAP,
        CONTROL_CLIENT_CODE,
        REPORT_IMAGE_HELPER,
    )
    prefix = (CONTROL_CLIENT_CODE + "\n\n" + REPORT_IMAGE_HELPER + "\n"
              + CONNECTION_BOOTSTRAP + "\n")
    if code.startswith(prefix):
        return code[len(prefix):]
    return code


def _literal_range_size(node: ast.AST, int_values: dict,
                        int_tuples: dict = None) -> int:
    """Iteration count of a `range(...)` call whose bounds are integer
    literals, names assigned integer literals, or subscripts of literal
    tuples (`range(grid_size[0])`), else 0."""
    int_tuples = int_tuples or {}
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "range"):
        return 0
    args = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
            args.append(arg.value)
        elif (isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub)
              and isinstance(arg.operand, ast.Constant)):
            args.append(-arg.operand.value)
        elif isinstance(arg, ast.Name) and arg.id in int_values:
            args.append(int_values[arg.id])
        elif (isinstance(arg, ast.Subscript)
              and isinstance(arg.value, ast.Name)
              and arg.value.id in int_tuples
              and isinstance(arg.slice, ast.Constant)
              and isinstance(arg.slice.value, int)
              and 0 <= arg.slice.value < len(int_tuples[arg.value.id])):
            args.append(int_tuples[arg.value.id][arg.slice.value])
        else:
            return 0
    if len(args) == 1:
        return max(0, args[0])
    if len(args) == 2:
        return max(0, args[1] - args[0])
    if len(args) == 3 and args[2] != 0:
        return max(0, -(-(args[1] - args[0]) // args[2]))
    return 0


def _iter_size(node: ast.AST, list_lengths: dict, int_values: dict,
               int_tuples: dict = None) -> int:
    """Iteration count of a loop iterable, resolving names assigned literal
    lists, ints, or int tuples elsewhere in the script."""
    int_tuples = int_tuples or {}
    size = _literal_range_size(node, int_values, int_tuples)
    if size:
        return size
    if isinstance(node, (ast.List, ast.Tuple)):
        return len(node.elts)
    if isinstance(node, ast.Name):
        return list_lengths.get(node.id, 0)
    # itertools.product(range(a), range(b)) and enumerate(...)
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "product":
            sizes = [_iter_size(a, list_lengths, int_values, int_tuples)
                     for a in node.args]
            if sizes and all(sizes):
                result = 1
                for s in sizes:
                    result *= s
                return result
        if name == "enumerate" and node.args:
            return _iter_size(node.args[0], list_lengths, int_values,
                              int_tuples)
    return 0


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        base = getattr(func.value, "id", "")
        return f"{base}.{func.attr}" if base else func.attr
    if isinstance(func, ast.Name):
        return func.id
    return "<call>"


def _numeric_literal(value: ast.AST):
    """int/float value of a (possibly negated or 10e3-style) literal, else None."""
    if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) \
            and not isinstance(value.value, bool):
        return value.value
    if (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub)):
        inner = _numeric_literal(value.operand)
        return -inner if inner is not None else None
    if isinstance(value, ast.BinOp) and isinstance(value.op, (ast.Mult, ast.Div)):
        left, right = _numeric_literal(value.left), _numeric_literal(value.right)
        if left is not None and right is not None:
            try:
                return left * right if isinstance(value.op, ast.Mult) else left / right
            except ZeroDivisionError:
                return None
    return None


def _collect_assignments(tree: ast.AST) -> tuple:
    """(int_values, numeric_values, int_tuples): variable name -> literal int
    (for range bounds), -> literal number (for magnifications/tilts), and ->
    tuple of literal ints (for `grid_size = (3, 3)` used as
    `range(grid_size[0])`). Covers `n = 3`, `rows, cols = 3, 3`,
    `n_rows = n_cols = 3` (chained), and `mag = 10e3` forms. A name assigned
    more than one distinct literal is dropped (ambiguous)."""
    ints, numerics, tuples, ambiguous = {}, {}, {}, set()

    def record(name, value):
        if name in ambiguous:
            return
        if isinstance(value, ast.Tuple):
            elems = [_numeric_literal(e) for e in value.elts]
            if elems and all(isinstance(e, int) for e in elems):
                if name in tuples and tuples[name] != tuple(elems):
                    ambiguous.add(name)
                    tuples.pop(name, None)
                else:
                    tuples[name] = tuple(elems)
            return
        number = _numeric_literal(value)
        if number is None:
            # Assigned something non-literal: any earlier literal is unsafe.
            if name in ints or name in numerics or name in tuples:
                ambiguous.add(name)
                ints.pop(name, None)
                numerics.pop(name, None)
                tuples.pop(name, None)
            return
        if name in numerics and numerics[name] != number:
            ambiguous.add(name)
            ints.pop(name, None)
            numerics.pop(name, None)
            return
        numerics[name] = number
        if isinstance(number, int):
            ints[name] = number

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:  # covers chained `a = b = 3`
            value = node.value
            if isinstance(target, ast.Name):
                record(target.id, value)
            elif (isinstance(target, ast.Tuple)
                  and isinstance(value, ast.Tuple)
                  and len(target.elts) == len(value.elts)):
                for t, v in zip(target.elts, value.elts):
                    if isinstance(t, ast.Name):
                        record(t.id, v)
    return ints, numerics, tuples


def extract_features(llm_code: str) -> dict:
    """Static plan features used to build the outcome distribution.

    The walk simulates enough of the script to count runtime behaviour, not
    code shape: literal loops are unrolled, and lists populated via
    `.append()`/`.extend()` inside counted loops resolve to their runtime
    length, so a fine pass written as `for pos in coarse_positions:` counts
    the same as an explicit second grid loop.
    """
    features = {
        "parse_error": False,
        "grid_shapes": [],       # loop-nest shapes in source order, e.g. ["3×3", "9"]
        "phase_acqs": [],        # acquisitions inside each top-level loop
        "preamble_acq": 0,       # acquisitions outside any loop
        "mode_sequence": [],     # set_mode argument sequence, e.g. ["IMG", "DIFF", ...]
        "tilts": [],             # (a, b) pairs passed to set_stage
        "magnifications": [],    # resolved set_magnification values
        "est_acquisitions": 0,   # acquire_image count with loops unrolled
        "has_nonliteral_loops": False,
        "computed_grid": False,  # a loop's range() is derived at runtime
    }
    try:
        tree = ast.parse(llm_code)
    except SyntaxError:
        features["parse_error"] = True
        return features

    # Locally defined helpers are inlined at each call site (guarded against
    # recursion) so `def take_image(...)`-style wrappers count correctly.
    local_funcs = {n.name: n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    inline_stack = set()

    int_values, numeric_values, int_tuples = _collect_assignments(tree)
    # Runtime lengths of lists, updated in source order as the walk simulates
    # assignments and append/extend calls.
    live_lists = {}
    # name -> [(a, b), ...] for literal lists of numeric 2-tuples or of
    # {"a": .., "b": ..} dicts, so tilt values survive both the
    # `for a, b in tilts:` and the `for tilt in tilt_conditions:
    # set_stage(tilt)` idioms.
    live_tuple_lists = {}
    live_dict_lists = {}
    handled_set_stage = set()

    def _tilt_pair_from_dict(node):
        if not isinstance(node, ast.Dict):
            return None
        pair = {}
        for key, value in zip(node.keys, node.values):
            key_name = getattr(key, "value", None)
            if key_name in ("a", "b"):
                number = _numeric_literal(value)
                if number is None:
                    return None
                pair[key_name] = number
        if not pair:
            return None
        return (pair.get("a"), pair.get("b"))

    def resolve_number(node):
        number = _numeric_literal(node)
        if number is None and isinstance(node, ast.Name):
            return numeric_values.get(node.id)
        return number

    def count_acq(multiplier, phase_idx):
        features["est_acquisitions"] += multiplier
        if phase_idx is None:
            features["preamble_acq"] += multiplier
        else:
            features["phase_acqs"][phase_idx] += multiplier

    def simulate_statement(node, multiplier):
        """Track list creation and growth so later loops resolve."""
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if isinstance(node.value, (ast.List, ast.Tuple)):
                live_lists[name] = len(node.value.elts)
                tuples = []
                for elt in node.value.elts:
                    if (isinstance(elt, (ast.Tuple, ast.List))
                            and len(elt.elts) == 2):
                        pair = tuple(_numeric_literal(e) for e in elt.elts)
                        if None not in pair:
                            tuples.append(pair)
                if tuples and len(tuples) == len(node.value.elts):
                    live_tuple_lists[name] = tuples
                else:
                    live_tuple_lists.pop(name, None)
                dict_pairs = [_tilt_pair_from_dict(e) for e in node.value.elts]
                if dict_pairs and all(p is not None for p in dict_pairs):
                    live_dict_lists[name] = dict_pairs
                else:
                    live_dict_lists.pop(name, None)
            else:
                live_lists.pop(name, None)  # unknown value
                live_tuple_lists.pop(name, None)
                live_dict_lists.pop(name, None)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                name = func.value.id
                if func.attr == "append" and name in live_lists:
                    live_lists[name] += multiplier
                elif func.attr == "extend" and name in live_lists:
                    if (node.value.args
                            and isinstance(node.value.args[0], (ast.List, ast.Tuple))):
                        live_lists[name] += multiplier * len(node.value.args[0].elts)
                    else:
                        live_lists.pop(name, None)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name in live_lists and isinstance(node.op, ast.Add) \
                    and isinstance(node.value, (ast.List, ast.Tuple)):
                live_lists[name] += multiplier * len(node.value.elts)
            else:
                live_lists.pop(name, None)

    def resolve_loop_tilts(node):
        """Credit literal tilt values applied through a loop, for both the
        `for a, b in tilts: set_stage({"a": a, "b": b})` idiom and the
        `for tilt in tilt_conditions: set_stage(tilt)` idiom."""
        if not isinstance(node.iter, ast.Name):
            return
        credited = False
        # Idiom 1: tuple unpacking into names used inside a dict literal.
        if (node.iter.id in live_tuple_lists
                and isinstance(node.target, ast.Tuple)):
            target_names = {e.id for e in node.target.elts
                            if isinstance(e, ast.Name)}
            for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
                if not (_call_name(call).endswith("set_stage") and call.args
                        and isinstance(call.args[0], ast.Dict)):
                    continue
                keys = {getattr(k, "value", None): v
                        for k, v in zip(call.args[0].keys, call.args[0].values)}
                tilt_args = [v for key, v in keys.items() if key in ("a", "b")]
                if tilt_args and all(isinstance(v, ast.Name)
                                     and v.id in target_names
                                     for v in tilt_args):
                    handled_set_stage.add(id(call))
                    credited = True
            if credited:
                features["tilts"].extend(live_tuple_lists[node.iter.id])
                return
        # Idiom 2: the loop dict passed to set_stage, either whole
        # (`set_stage(tilt)`) or re-keyed by subscripting
        # (`set_stage({"a": tilt["a"], "b": tilt["b"]})`).
        if (node.iter.id in live_dict_lists
                and isinstance(node.target, ast.Name)):
            target = node.target.id
            # `alpha = tilt["a"]`-style aliases of the loop dict's entries.
            aliases = {}
            for stmt in ast.walk(node):
                if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                        and isinstance(stmt.value, ast.Subscript)
                        and isinstance(stmt.value.value, ast.Name)
                        and stmt.value.value.id == target
                        and getattr(stmt.value.slice, "value", None) in ("a", "b")):
                    aliases[stmt.targets[0].id] = stmt.value.slice.value

            def comes_from_target(key_name, value):
                if (isinstance(value, ast.Subscript)
                        and isinstance(value.value, ast.Name)
                        and value.value.id == target):
                    return getattr(value.slice, "value", None) == key_name
                if isinstance(value, ast.Name):
                    return aliases.get(value.id) == key_name
                return False

            for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
                if not (_call_name(call).endswith("set_stage") and call.args):
                    continue
                arg = call.args[0]
                passthrough = isinstance(arg, ast.Name) and arg.id == target
                subscripted = False
                if isinstance(arg, ast.Dict):
                    tilt_pairs = [(getattr(k, "value", None), v)
                                  for k, v in zip(arg.keys, arg.values)
                                  if getattr(k, "value", None) in ("a", "b")]
                    subscripted = bool(tilt_pairs) and all(
                        comes_from_target(key, v) for key, v in tilt_pairs)
                if passthrough or subscripted:
                    handled_set_stage.add(id(call))
                    credited = True
            if credited:
                features["tilts"].extend(live_dict_lists[node.iter.id])

    def walk(body, multiplier, depth, phase_idx):
        for node in body:
            if isinstance(node, (ast.For, ast.AsyncFor)):
                resolve_loop_tilts(node)
                size = _iter_size(node.iter, live_lists, int_values,
                                  int_tuples)
                if size == 0:
                    features["has_nonliteral_loops"] = True
                    if (isinstance(node.iter, ast.Call)
                            and isinstance(node.iter.func, ast.Name)
                            and node.iter.func.id == "range"):
                        features["computed_grid"] = True
                    inner_mult = multiplier  # count body once
                else:
                    inner_mult = multiplier * size
                if depth == 0:
                    # Record loop-nest shape: NxM for a directly nested
                    # resolvable loop, else the flat size.
                    inner_fors = [n for n in node.body
                                  if isinstance(n, (ast.For, ast.AsyncFor))]
                    inner_sizes = [_iter_size(f.iter, live_lists, int_values,
                                              int_tuples)
                                   for f in inner_fors]
                    if size and len(inner_fors) == 1 and inner_sizes[0]:
                        features["grid_shapes"].append(f"{size}×{inner_sizes[0]}")
                    else:
                        features["grid_shapes"].append(str(size) if size else "?")
                    features["phase_acqs"].append(0)
                    walk(node.body, inner_mult, depth + 1,
                         len(features["phase_acqs"]) - 1)
                else:
                    walk(node.body, inner_mult, depth + 1, phase_idx)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Bodies are counted at each CALL site via inlining, not at
                # the definition.
                continue
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.While)):
                if isinstance(node, ast.While):
                    features["has_nonliteral_loops"] = True
                walk(node.body, multiplier, depth, phase_idx)
                for extra in getattr(node, "orelse", []) or []:
                    walk([extra], multiplier, depth, phase_idx)
                for handler in getattr(node, "handlers", []) or []:
                    walk(handler.body, multiplier, depth, phase_idx)
                if getattr(node, "finalbody", None):
                    walk(node.finalbody, multiplier, depth, phase_idx)
            else:
                simulate_statement(node, multiplier)
                for call in [n for n in ast.walk(node)
                             if isinstance(n, ast.Call)]:
                    name = _call_name(call)
                    if (isinstance(call.func, ast.Name)
                            and call.func.id in local_funcs
                            and call.func.id not in inline_stack):
                        inline_stack.add(call.func.id)
                        walk(local_funcs[call.func.id].body, multiplier,
                             depth, phase_idx)
                        inline_stack.discard(call.func.id)
                    elif name.endswith("acquire_image"):
                        count_acq(multiplier, phase_idx)
                    elif name.endswith("set_mode") and call.args:
                        if isinstance(call.args[0], ast.Constant):
                            features["mode_sequence"].append(
                                str(call.args[0].value))
                    elif name.endswith("set_magnification") and call.args:
                        value = resolve_number(call.args[0])
                        if value is not None:
                            features["magnifications"].append(value)
                    elif name.endswith("set_stage") and call.args:
                        if id(call) in handled_set_stage:
                            continue
                        if isinstance(call.args[0], ast.Dict):
                            keys = {getattr(k, "value", None): v
                                    for k, v in zip(call.args[0].keys,
                                                    call.args[0].values)}
                            if "a" in keys or "b" in keys:
                                features["tilts"].append(
                                    (resolve_number(keys.get("a"))
                                     if keys.get("a") is not None else None,
                                     resolve_number(keys.get("b"))
                                     if keys.get("b") is not None else None))

    walk(tree.body, 1, 0, None)
    return features


def _fmt_num(value) -> str:
    return "?" if value is None else f"{value:g}"


def plan_signature(features: dict, has_code: bool) -> str:
    """Canonical outcome label for the distribution tables.

    Deliberately BEHAVIOURAL: two scripts that acquire the same images with
    the same parameters share a signature even if one writes an explicit
    second grid loop and the other revisits a stored position list. Loop
    structure (code idiom) is reported separately, not here.
    """
    if not has_code:
        return "no code block"
    if features["parse_error"]:
        return "unparseable code"
    parts = []
    layout = []
    if features["preamble_acq"]:
        layout.append(str(features["preamble_acq"]))
    layout.extend(str(count) for count in features["phase_acqs"] if count)
    prefix = "≥" if features["has_nonliteral_loops"] else ""
    total = features["est_acquisitions"]
    if len(layout) > 1:
        parts.append(f"acquisitions {prefix}{'+'.join(layout)} = {total}")
    else:
        parts.append(f"acquisitions {prefix}{total}")
    tilts = [(a, b) for a, b in features["tilts"]
             if a is not None or b is not None]
    if tilts:
        parts.append("tilts " + ",".join(
            f"({_fmt_num(a)},{_fmt_num(b)})" for a, b in tilts))
    if features["mode_sequence"]:
        parts.append(f"{len(features['mode_sequence'])} mode switches")
    if features["magnifications"]:
        mags = sorted(set(features["magnifications"]))
        parts.append("mags " + "/".join(_fmt_num(m) for m in mags))
    if features["computed_grid"]:
        parts.append("runtime-computed grid size")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Manuscript-style step outline
# ---------------------------------------------------------------------------

def build_outline(llm_code: str, max_steps: int = 60) -> list:
    """Ordered (step_number, action, details) rows for a Table 1-4 style table.

    Loops become a single "For each ..." row with numbered sub-steps, matching
    how the manuscript tables describe iterated actions.
    """
    INTERESTING = {"set_mode", "set_stage", "set_magnification", "set_beam",
                   "acquire_image", "autofocus", "report_image",
                   "set_diffraction_settings", "get_stage", "get_microscope_state"}
    try:
        tree = ast.parse(llm_code)
    except SyntaxError:
        return [("1", "unparseable code", "")]

    rows = []

    def emit(prefix, body, counter):
        """Emit rows for `body`; returns the updated step counter so that
        transparent blocks (if/try/with) continue numbering instead of
        restarting it."""
        for node in body:
            if len(rows) >= max_steps:
                return counter
            if isinstance(node, (ast.For, ast.AsyncFor)):
                counter += 1
                number = f"{prefix}{counter}"
                target = ast.unparse(node.target)
                iterator = ast.unparse(node.iter)
                rows.append((number, f"For each `{target}` in `{iterator}`", ""))
                emit(number + ".", node.body, 0)
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                counter = emit(prefix, node.body, counter)
                for handler in getattr(node, "handlers", []) or []:
                    counter = emit(prefix, handler.body, counter)
            else:
                for call in [n for n in ast.walk(node)
                             if isinstance(n, ast.Call)]:
                    name = _call_name(call)
                    short = name.split(".")[-1]
                    if short in INTERESTING:
                        counter += 1
                        args = ", ".join(
                            [ast.unparse(a) for a in call.args]
                            + [f"{kw.arg}={ast.unparse(kw.value)}"
                               for kw in call.keywords]
                        )
                        rows.append((f"{prefix}{counter}", short, args))
        return counter

    emit("", tree.body, 0)
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _distribution(counter: Counter) -> str:
    return "; ".join(f"{label}: {count}" for label, count in counter.most_common())


def build_report(out_dir: Path, runs_expected: int, temperatures: list,
                 prompt_ids: list) -> None:
    jsonl_path = out_dir / "results.jsonl"
    if not jsonl_path.exists():
        sys.exit(f"No results at {jsonl_path}; run the study first.")

    # Latest record wins per (prompt, temperature, run) so resumed retries
    # supersede earlier failures.
    records = {}
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        records[_run_key(record)] = record
    records = sorted(records.values(),
                     key=lambda r: (r["prompt_id"], r["temperature"], r["run"]))

    resolved_models = set()
    audit_path = out_dir / "llm_calls.jsonl"
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            try:
                resolved = json.loads(line).get("resolved_model")
                if resolved:
                    resolved_models.add(resolved)
            except json.JSONDecodeError:
                continue

    analysed = []
    for record in records:
        code = record.get("generated_code")
        llm_code = strip_boilerplate(code) if code else ""
        features = extract_features(llm_code) if code else None
        analysed.append({
            **record,
            "llm_code": llm_code,
            "features": features,
            "signature": plan_signature(features or {}, bool(code)),
        })

    lines = []
    add = lines.append
    add("# Temperature ablation results")
    add("")
    add(f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    add(f"- Design: prompts {prompt_ids} × temperatures {temperatures} × "
        f"N={runs_expected} runs (fresh chat per run, UI-identical payload, "
        f"experiment_config=None)")
    add(f"- Model snapshot(s) served by the API: "
        f"{', '.join(sorted(resolved_models)) or 'unknown (no audit log)'}")
    add("- Outcome labels are BEHAVIOURAL plan signatures extracted from the "
        "generated script by AST analysis: per-phase and total "
        "`acquire_image` counts with loops unrolled (including lists "
        "populated via append inside counted loops), tilt values, "
        "mode-switch count, and magnifications. '≥' marks plans containing "
        "a loop whose iteration count could not be resolved statically "
        "(the true count is at least the number shown). Loop structure "
        "(explicit nested grid loop vs. revisiting a stored position list) "
        "is reported separately per prompt and deliberately excluded from "
        "the signature: it is a code idiom, not an experimental outcome.")
    if (out_dir / "validation.md").exists():
        add("- Ground truth: a sample of these scripts was executed against "
            "the digital twin through the production sandbox; see "
            "validation.md for actual acquisition counts from the twin's "
            "server-side command log.")
    add("")

    # ------------------------------------------------------------------ summary
    add("## Summary")
    add("")
    add("| Prompt | T | Runs ok | Code produced | Distinct plans | "
        "Modal plan share | Coarse grid (distribution) | "
        "Total acquisitions (distribution) |")
    add("|---|---|---|---|---|---|---|---|")
    for pid in prompt_ids:
        for temperature in temperatures:
            group = [a for a in analysed
                     if a["prompt_id"] == pid
                     and a["temperature"] == temperature]
            ok = [a for a in group if not a["error"]]
            with_code = [a for a in ok if a["generated_code"]]
            signatures = Counter(a["signature"] for a in ok)
            modal_share = (f"{signatures.most_common(1)[0][1]}/{len(ok)}"
                           if ok else "—")
            grids = Counter(
                (a["features"]["grid_shapes"][0]
                 if a["features"]["grid_shapes"] else "none")
                for a in with_code if not a["features"]["parse_error"])
            acqs = Counter(
                f"{'≥' if a['features']['has_nonliteral_loops'] else ''}"
                f"{a['features']['est_acquisitions']}"
                for a in with_code if not a["features"]["parse_error"])
            add(f"| P{pid} | {temperature} | {len(ok)}/{len(group)} "
                f"| {len(with_code)}/{len(ok) or 1} | {len(signatures)} "
                f"| {modal_share} | {_md_escape(_distribution(grids)) or '—'} "
                f"| {_md_escape(_distribution(acqs)) or '—'} |")
    add("")

    # ------------------------------------------------------- per-prompt detail
    for pid in prompt_ids:
        add(f"## Prompt {pid}")
        add("")
        add("> " + PROMPTS[pid].replace("\n", "\n> "))
        add("")
        add("### Outcome distribution by temperature")
        add("")
        add("| T | Plan signature | Count |")
        add("|---|---|---|")
        for temperature in temperatures:
            ok = [a for a in analysed
                  if a["prompt_id"] == pid and a["temperature"] == temperature
                  and not a["error"]]
            for signature, count in Counter(
                    a["signature"] for a in ok).most_common():
                add(f"| {temperature} | {_md_escape(signature)} | {count} |")
        add("")

        # Code idiom: how the plan was written, independent of what it does.
        structures = Counter()
        for a in analysed:
            if (a["prompt_id"] == pid and not a["error"] and a["features"]
                    and not a["features"]["parse_error"]):
                structures["+".join(a["features"]["grid_shapes"]) or "no loops"] += 1
        if structures:
            add(f"Loop structures across all temperatures (code idiom, not "
                f"part of the signature): {_distribution(structures)}")
            add("")

        # Extra distributions that matter per prompt family
        mags = Counter()
        for a in analysed:
            if (a["prompt_id"] == pid and not a["error"] and a["features"]
                    and not a["features"]["parse_error"]
                    and a["features"]["magnifications"]):
                mags["/".join(_fmt_num(m) for m in
                              sorted(set(a["features"]["magnifications"])))] += 1
        if mags:
            add(f"Magnification value sets across all temperatures: "
                f"{_distribution(mags)}")
            add("")

        # Representative (modal) plan at the manuscript's operating point.
        operating_t = 0.3 if 0.3 in temperatures else temperatures[0]
        candidates = [a for a in analysed
                      if a["prompt_id"] == pid
                      and a["temperature"] == operating_t
                      and not a["error"] and a["generated_code"]]
        if candidates:
            modal_sig = Counter(
                a["signature"] for a in candidates).most_common(1)[0][0]
            representative = next(
                a for a in candidates if a["signature"] == modal_sig)
            add(f"### Representative plan (modal signature at "
                f"T={operating_t}, run {representative['run']})")
            add("")
            add("| Step | Action | Parameters |")
            add("|---|---|---|")
            for number, action, details in build_outline(
                    representative["llm_code"]):
                add(f"| {number} | {_md_escape(action)} "
                    f"| {_md_escape(details)} |")
            add("")

    # --------------------------------------------------------------- appendix
    add("## Appendix: all runs")
    add("")
    for a in analysed:
        add(f"### P{a['prompt_id']} / T={a['temperature']} / run {a['run']}")
        add("")
        if a["error"]:
            add(f"**FAILED after {a['attempts']} attempts:** {a['error']}")
            add("")
            continue
        add(f"Signature: `{a['signature']}`")
        add("")
        add("Assistant message:")
        add("")
        add(a["message"] or "(empty)")
        add("")
        if a["llm_code"]:
            add("Generated script (LLM-authored part; portable client "
                "boilerplate stripped):")
            add("")
            add("````python")
            add(a["llm_code"])
            add("````")
            add("")

    report_path = out_dir / "results.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {report_path}")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--temperatures", type=float, nargs="+",
                        default=DEFAULT_TEMPERATURES)
    parser.add_argument("--prompts", type=int, nargs="+",
                        default=sorted(PROMPTS), choices=sorted(PROMPTS))
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--out", type=Path,
                        default=BACKEND_ROOT / "ablation")
    parser.add_argument("--report-only", action="store_true",
                        help="Rebuild results.md from existing results.jsonl")
    args = parser.parse_args()

    if not args.report_only:
        asyncio.run(run_study(args.runs, args.temperatures, args.prompts,
                              args.concurrency, args.out))
    build_report(args.out, args.runs, args.temperatures, args.prompts)


if __name__ == "__main__":
    main()
