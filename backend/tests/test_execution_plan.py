"""Tests for ExecutionPlan model and JSON extraction logic."""

import json
import pytest
from app.models.schemas import ExecutionStep, ExecutionPlan


class TestExecutionStepModel:
    def test_minimal_step(self):
        step = ExecutionStep(action="acquire", params={}, description="")
        assert step.action == "acquire"

    def test_step_with_params(self):
        step = ExecutionStep(
            action="tilt",
            params={"a": 10, "b": 0, "relative": False},
            description="Tilt to 10 deg",
        )
        assert step.params["a"] == 10
        assert step.description == "Tilt to 10 deg"

    def test_step_requires_action(self):
        with pytest.raises(Exception):
            ExecutionStep(params={}, description="no action")


class TestExecutionPlanModel:
    def test_valid_plan(self):
        plan = ExecutionPlan(
            plan_type="tilt_series",
            steps=[
                ExecutionStep(action="tilt", params={"a": 0}, description="Zero tilt"),
                ExecutionStep(action="acquire", params={}, description="Capture"),
            ],
            summary="Simple tilt series",
        )
        assert plan.plan_type == "tilt_series"
        assert len(plan.steps) == 2

    def test_empty_steps(self):
        plan = ExecutionPlan(plan_type="custom", steps=[], summary="empty")
        assert plan.steps == []

    def test_from_dict(self):
        data = {
            "plan_type": "grid_scan",
            "steps": [{"action": "move", "params": {"x_um": 5}, "description": "move"}],
            "summary": "scan",
        }
        plan = ExecutionPlan(**data)
        assert plan.steps[0].action == "move"

    def test_from_json_string(self):
        raw = json.dumps({
            "plan_type": "single_acquisition",
            "steps": [{"action": "acquire", "params": {}, "description": "snap"}],
            "summary": "take a photo",
        })
        plan = ExecutionPlan(**json.loads(raw))
        assert plan.plan_type == "single_acquisition"


class TestExtractExecutionPlan:
    """Test the _extract_execution_plan function from chat.py."""

    def _extract(self, text: str):
        # Import the private function
        from app.routes.chat import _extract_execution_plan
        return _extract_execution_plan(text)

    def test_valid_json_block(self):
        text = '''Here is your code:
```python
stem.acquire_image("haadf")
```

```json
{
  "plan_type": "single_acquisition",
  "steps": [{"action": "acquire", "params": {}, "description": "snap"}],
  "summary": "Acquire one image"
}
```
'''
        plan = self._extract(text)
        assert plan is not None
        assert plan.plan_type == "single_acquisition"
        assert len(plan.steps) == 1

    def test_no_json_block(self):
        plan = self._extract("Just some text with no code blocks.")
        assert plan is None

    def test_json_block_without_plan_fields(self):
        text = '```json\n{"key": "value"}\n```'
        plan = self._extract(text)
        assert plan is None

    def test_malformed_json(self):
        text = '```json\n{this is not valid json}\n```'
        plan = self._extract(text)
        assert plan is None

    def test_multiple_json_blocks_picks_plan(self):
        text = '''```json
{"some": "other data"}
```

```json
{
  "plan_type": "tilt_series",
  "steps": [{"action": "tilt", "params": {"a": 10}, "description": "tilt"}],
  "summary": "tilt"
}
```'''
        plan = self._extract(text)
        assert plan is not None
        assert plan.plan_type == "tilt_series"
