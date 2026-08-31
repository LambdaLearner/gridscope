"""Tests for the static plan analysis in scripts/temperature_ablation.py —
the ablation's outcome distributions are only as trustworthy as this
extraction, so pin its behaviour on representative generated-script shapes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from temperature_ablation import (  # noqa: E402
    PROMPTS,
    build_outline,
    extract_features,
    plan_signature,
)


TILT_SERIES_SCRIPT = """\
tilts = [(0, 0), (20, 18), (28, 25)]
for a, b in tilts:
    mic.set_stage({"a": a, "b": b}, relative=False)
    mic.set_mode("IMG")
    img = mic.acquire_image("haadf")
    report_image(img, label=f"IMG a={a}")
    mic.set_mode("DIFF")
    diff = mic.acquire_image("haadf")
    report_image(diff, label=f"DIFF a={a}")
mic.set_mode("IMG")
"""

GRID_SCRIPT = """\
mic.set_magnification(5000)
for i in range(3):
    for j in range(3):
        mic.set_stage({"x": i * 5e-6, "y": j * 5e-6}, relative=False)
        img = mic.acquire_image("haadf")
        report_image(img)
mic.set_magnification(20000)
for i in range(3):
    for j in range(3):
        mic.set_stage({"x": i * 5e-6, "y": j * 5e-6}, relative=False)
        img = mic.acquire_image("haadf")
        report_image(img)
"""

EXPLICIT_TILT_SCRIPT = """\
mic.set_stage({"a": 0, "b": 0}, relative=False)
img = mic.acquire_image("haadf")
mic.set_stage({"a": 28, "b": -25}, relative=False)
img = mic.acquire_image("haadf")
"""

NONLITERAL_LOOP_SCRIPT = """\
positions = compute_positions()
for pos in positions:
    mic.set_stage(pos, relative=False)
    img = mic.acquire_image("haadf")
"""

# The two coding idioms GPT-4o uses for the same coarse-to-fine behaviour:
# an explicit second literal grid loop vs. revisiting a stored position list.
# Both acquire 9 + 9 images with the same magnifications — they MUST share a
# plan signature (this was a real bug: the append-populated list was not
# resolved and the revisit loop was undercounted as 10).
FINE_LOOP_IDIOM = """\
mic.set_magnification(10000)
for row in range(3):
    for col in range(3):
        mic.set_stage({"x": row * 1e-6, "y": col * 1e-6}, relative=False)
        img = mic.acquire_image("haadf")
        report_image(img)
mic.set_magnification(50000)
for row in range(3):
    for col in range(3):
        mic.set_stage({"x": row * 1e-6, "y": col * 1e-6}, relative=False)
        img = mic.acquire_image("haadf")
        report_image(img)
"""

REVISIT_LIST_IDIOM = """\
coarse_magnification = 10e3
fine_magnification = 50e3
mic.set_magnification(coarse_magnification)
coarse_positions = []
for row in range(3):
    for col in range(3):
        try:
            mic.set_stage({"x": row * 1e-6, "y": col * 1e-6}, relative=False)
            img = mic.acquire_image("haadf")
            report_image(img)
            coarse_positions.append((row, col))
        except RuntimeError as e:
            print(e)
mic.set_magnification(fine_magnification)
for idx, (x, y) in enumerate(coarse_positions):
    mic.set_stage({"x": x, "y": y}, relative=False)
    img = mic.acquire_image("haadf")
    report_image(img)
"""

# range() over variables assigned literal ints — the shape LLM scripts
# actually favour (and how the smoke-test run was written).
VARIABLE_GRID_SCRIPT = """\
rows, cols = 3, 3
mic.set_magnification(10000)
for row in range(rows):
    for col in range(cols):
        try:
            mic.set_stage({"x": row * 1e-6, "y": col * 1e-6}, relative=False)
        except RuntimeError as e:
            print(e)
            continue
        img = mic.acquire_image("haadf")
        report_image(img)
"""


class TestExtractFeatures:
    def test_tilt_series_features(self):
        features = extract_features(TILT_SERIES_SCRIPT)
        assert not features["parse_error"]
        # 3 tilt positions × (IMG + DIFF) acquisitions
        assert features["est_acquisitions"] == 6
        assert features["grid_shapes"] == ["3"]
        # 2 switches per iteration unrolled once each in sequence order,
        # plus the trailing reset
        assert features["mode_sequence"] == ["IMG", "DIFF", "IMG"]
        # Tilt values resolved through the `for a, b in tilts:` idiom
        assert features["tilts"] == [(0, 0), (20, 18), (28, 25)]

    def test_nested_grid_features(self):
        features = extract_features(GRID_SCRIPT)
        assert features["grid_shapes"] == ["3×3", "3×3"]
        assert features["est_acquisitions"] == 18
        assert features["magnifications"] == [5000, 20000]
        assert not features["has_nonliteral_loops"]

    def test_explicit_tilts_with_negatives(self):
        features = extract_features(EXPLICIT_TILT_SCRIPT)
        assert features["tilts"] == [(0, 0), (28, -25)]
        assert features["est_acquisitions"] == 2

    def test_nonliteral_loop_flagged(self):
        features = extract_features(NONLITERAL_LOOP_SCRIPT)
        assert features["has_nonliteral_loops"]
        # Body counted once when the loop size is unknown
        assert features["est_acquisitions"] == 1

    def test_syntax_error_reported_not_raised(self):
        features = extract_features("def broken(:")
        assert features["parse_error"]

    def test_grid_via_int_variables_resolved(self):
        features = extract_features(VARIABLE_GRID_SCRIPT)
        assert features["grid_shapes"] == ["3×3"]
        assert features["est_acquisitions"] == 9
        assert not features["has_nonliteral_loops"]

    def test_reassigned_int_variable_is_ambiguous(self):
        code = "n = 2\nfor i in range(n):\n    mic.acquire_image('haadf')\nn = 5\n"
        features = extract_features(code)
        assert features["has_nonliteral_loops"]
        assert features["est_acquisitions"] == 1

    def test_append_populated_list_resolves_revisit_loop(self):
        features = extract_features(REVISIT_LIST_IDIOM)
        # 9 coarse appends inside the 3×3 loop -> the revisit loop is 9 long
        assert features["phase_acqs"] == [9, 9]
        assert features["est_acquisitions"] == 18
        assert not features["has_nonliteral_loops"]

    def test_magnifications_resolved_through_variables(self):
        features = extract_features(REVISIT_LIST_IDIOM)
        assert features["magnifications"] == [10000.0, 50000.0]

    def test_local_helper_functions_inlined_at_call_sites(self):
        # Acquisitions inside a def must count once per call, not once per
        # definition (real bug: a P2 run scored 1 instead of 18).
        code = (
            "def snap(fov, label):\n"
            "    mic.device_settings('haadf', field_of_view_um=fov)\n"
            "    img = mic.acquire_image('haadf')\n"
            "    report_image(img, label=label)\n"
            "for row in range(3):\n"
            "    for col in range(3):\n"
            "        snap(7.0, 'coarse')\n"
            "        snap(2.5, 'fine')\n"
        )
        features = extract_features(code)
        assert features["est_acquisitions"] == 18
        assert not features["has_nonliteral_loops"]

    def test_recursive_helper_does_not_hang(self):
        code = (
            "def loop():\n"
            "    mic.acquire_image('haadf')\n"
            "    loop()\n"
            "loop()\n"
        )
        features = extract_features(code)
        assert features["est_acquisitions"] == 1

    def test_tilt_dict_list_idiom_resolved(self):
        code = (
            'tilt_conditions = [{"a": 0, "b": 0}, {"a": 20, "b": 18},'
            ' {"a": 28, "b": 25}]\n'
            "for tilt in tilt_conditions:\n"
            "    mic.set_stage(tilt, relative=False)\n"
            "    img = mic.acquire_image('haadf')\n"
        )
        features = extract_features(code)
        assert features["tilts"] == [(0, 0), (20, 18), (28, 25)]
        assert features["est_acquisitions"] == 3

    def test_both_tilt_idioms_share_a_signature(self):
        dict_idiom = (
            'tilts = [{"a": 0, "b": 0}, {"a": 20, "b": 18}, {"a": 28, "b": 25}]\n'
            "for t in tilts:\n"
            "    mic.set_stage(t, relative=False)\n"
            "    img = mic.acquire_image('haadf')\n"
        )
        tuple_idiom = (
            "tilts = [(0, 0), (20, 18), (28, 25)]\n"
            "for a, b in tilts:\n"
            '    mic.set_stage({"a": a, "b": b}, relative=False)\n'
            "    img = mic.acquire_image('haadf')\n"
        )
        assert (plan_signature(extract_features(dict_idiom), True)
                == plan_signature(extract_features(tuple_idiom), True))

    def test_tilt_dict_subscript_idiom_resolved(self):
        code = (
            'tilt_conditions = [{"a": 0, "b": 0}, {"a": 20, "b": 18},'
            ' {"a": 28, "b": 25}]\n'
            "for tilt in tilt_conditions:\n"
            '    mic.set_stage({"a": tilt["a"], "b": tilt["b"]},'
            " relative=False)\n"
            "    img = mic.acquire_image('haadf')\n"
        )
        features = extract_features(code)
        assert features["tilts"] == [(0, 0), (20, 18), (28, 25)]

    def test_chained_assignment_resolved(self):
        code = (
            "n_rows = n_cols = 3\n"
            "for i in range(n_rows):\n"
            "    for j in range(n_cols):\n"
            "        mic.acquire_image('haadf')\n"
        )
        features = extract_features(code)
        assert features["grid_shapes"] == ["3×3"]
        assert features["est_acquisitions"] == 9
        assert not features["has_nonliteral_loops"]

    def test_tuple_subscript_grid_resolved(self):
        code = (
            "grid_size = (3, 3)\n"
            "for i in range(grid_size[0]):\n"
            "    for j in range(grid_size[1]):\n"
            "        mic.acquire_image('haadf')\n"
        )
        features = extract_features(code)
        assert features["grid_shapes"] == ["3×3"]
        assert features["est_acquisitions"] == 9
        assert not features["has_nonliteral_loops"]

    def test_tilt_dict_alias_idiom_resolved(self):
        code = (
            'tilt_conditions = [{"a": 0, "b": 0}, {"a": 20, "b": 18},'
            ' {"a": 28, "b": 25}]\n'
            "for condition in tilt_conditions:\n"
            '    alpha = condition["a"]\n'
            '    beta = condition["b"]\n'
            '    mic.set_stage({"a": alpha, "b": beta}, relative=False)\n'
            "    img = mic.acquire_image('haadf')\n"
        )
        features = extract_features(code)
        assert features["tilts"] == [(0, 0), (20, 18), (28, 25)]

    def test_runtime_computed_grid_flagged(self):
        code = (
            "fov = mic.get_magnification(device='haadf')['field_of_view_um']\n"
            "tiles = int(fov / 2.5) + 1\n"
            "for row in range(tiles):\n"
            "    mic.acquire_image('haadf')\n"
        )
        features = extract_features(code)
        assert features["computed_grid"]
        signature = plan_signature(features, has_code=True)
        assert "runtime-computed grid size" in signature


class TestPlanSignature:
    def test_no_code_and_parse_error_labels(self):
        assert plan_signature({}, has_code=False) == "no code block"
        assert plan_signature({"parse_error": True}, True) == "unparseable code"

    def test_grid_script_signature_is_behavioural(self):
        features = extract_features(GRID_SCRIPT)
        signature = plan_signature(features, has_code=True)
        assert "acquisitions 9+9 = 18" in signature
        assert "mags 5000/20000" in signature

    def test_different_grids_get_different_signatures(self):
        small = GRID_SCRIPT.replace("range(3)", "range(2)")
        assert (plan_signature(extract_features(GRID_SCRIPT), True)
                != plan_signature(extract_features(small), True))

    def test_equivalent_idioms_share_a_signature(self):
        # The critical property: same behaviour, different code style ->
        # identical signature.
        sig_loop = plan_signature(extract_features(FINE_LOOP_IDIOM), True)
        sig_revisit = plan_signature(extract_features(REVISIT_LIST_IDIOM), True)
        assert sig_loop == sig_revisit
        assert "acquisitions 9+9 = 18" in sig_loop

    def test_unresolved_loop_marked_as_lower_bound(self):
        signature = plan_signature(extract_features(NONLITERAL_LOOP_SCRIPT),
                                   has_code=True)
        assert "≥1" in signature


class TestBuildOutline:
    def test_outline_orders_and_numbers_steps(self):
        rows = build_outline(GRID_SCRIPT)
        numbers = [r[0] for r in rows]
        assert numbers[0] == "1"          # set_magnification(5000)
        assert rows[0][1] == "set_magnification"
        assert rows[1][1].startswith("For each")
        # Sub-steps of the first loop are numbered 2.x
        assert any(n.startswith("2.") for n in numbers)

    def test_outline_survives_syntax_errors(self):
        assert build_outline("for (:") == [("1", "unparseable code", "")]

    def test_try_blocks_do_not_restart_numbering(self):
        rows = build_outline(VARIABLE_GRID_SCRIPT)
        numbers = [r[0] for r in rows]
        assert len(numbers) == len(set(numbers)), f"duplicate steps: {numbers}"


class TestPrompts:
    def test_revised_values_present_and_originals_absent(self):
        assert "(28°,25°)" in PROMPTS[1] and "(35,35)" not in PROMPTS[1]
        assert "7 µm" in PROMPTS[2] and "30" not in PROMPTS[2].split("overlap")[0].split("of ")[1][:3]
        assert "2.5 µm" in PROMPTS[2]
        assert len(PROMPTS) == 4
