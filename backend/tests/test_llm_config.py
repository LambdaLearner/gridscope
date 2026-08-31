"""Tests for llm_config.py — the pinned model/temperature defaults, env
overrides, the call audit log, and consistency with the README (the manuscript
cites the exact snapshot, so docs and code must not drift)."""

import json
from pathlib import Path

import pytest

from app.services.llm_config import (
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    LLM_LOG_PATH_ENV,
    get_model,
    get_temperature,
    log_llm_call,
)


README_PATH = Path(__file__).resolve().parents[2] / "README.md"


class TestModel:
    def test_default_is_pinned_snapshot(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        assert get_model() == DEFAULT_MODEL == "gpt-4o-2024-08-06"

    def test_default_is_not_a_floating_alias(self):
        # A bare alias would silently change behaviour when OpenAI repoints it.
        assert DEFAULT_MODEL != "gpt-4o"
        assert DEFAULT_MODEL != "gpt-4"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-2024-05-13")
        assert get_model() == "gpt-4o-2024-05-13"

    def test_readme_states_the_pinned_snapshot(self):
        readme = README_PATH.read_text(encoding="utf-8")
        assert DEFAULT_MODEL in readme, (
            "README.md must state the pinned model snapshot; it is cited in "
            "the manuscript and must not drift from the code."
        )


class TestTemperature:
    def test_default_is_zero(self, monkeypatch):
        monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
        assert get_temperature() == DEFAULT_TEMPERATURE == 0.0

    def test_empty_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OPENAI_TEMPERATURE", "  ")
        assert get_temperature() == DEFAULT_TEMPERATURE

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_TEMPERATURE", "0.7")
        assert get_temperature() == 0.7

    @pytest.mark.parametrize("boundary", ["0", "2"])
    def test_boundaries_accepted(self, monkeypatch, boundary):
        monkeypatch.setenv("OPENAI_TEMPERATURE", boundary)
        assert get_temperature() == float(boundary)

    @pytest.mark.parametrize("bad", ["abc", "0.5.1", ""])
    def test_non_numeric_raises(self, monkeypatch, bad):
        if bad == "":
            # Empty string is treated as unset, not an error.
            monkeypatch.setenv("OPENAI_TEMPERATURE", bad)
            assert get_temperature() == DEFAULT_TEMPERATURE
            return
        monkeypatch.setenv("OPENAI_TEMPERATURE", bad)
        with pytest.raises(ValueError, match="OPENAI_TEMPERATURE"):
            get_temperature()

    @pytest.mark.parametrize("out_of_range", ["-0.1", "2.1", "100"])
    def test_out_of_range_raises(self, monkeypatch, out_of_range):
        monkeypatch.setenv("OPENAI_TEMPERATURE", out_of_range)
        with pytest.raises(ValueError, match="between 0 and 2"):
            get_temperature()


class _FakeUsage:
    prompt_tokens = 123
    completion_tokens = 45


class _FakeResponse:
    model = "gpt-4o-2024-08-06"
    usage = _FakeUsage()


class TestCallLog:
    def test_writes_jsonl_record(self, monkeypatch, tmp_path):
        log_path = tmp_path / "llm_calls.jsonl"
        monkeypatch.setenv(LLM_LOG_PATH_ENV, str(log_path))

        log_llm_call("chat", "gpt-4o", 0.0, _FakeResponse())

        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["purpose"] == "chat"
        assert record["requested_model"] == "gpt-4o"
        assert record["resolved_model"] == "gpt-4o-2024-08-06"
        assert record["temperature"] == 0.0
        assert record["prompt_tokens"] == 123
        assert record["completion_tokens"] == 45
        assert record["timestamp"]

    def test_appends_across_calls(self, monkeypatch, tmp_path):
        log_path = tmp_path / "llm_calls.jsonl"
        monkeypatch.setenv(LLM_LOG_PATH_ENV, str(log_path))

        log_llm_call("chat", "gpt-4o", 0.0, _FakeResponse())
        log_llm_call("code_generation", "gpt-4o", 0.7, _FakeResponse())

        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1])["purpose"] == "code_generation"

    def test_missing_response_fields_logged_as_none(self, monkeypatch, tmp_path):
        log_path = tmp_path / "llm_calls.jsonl"
        monkeypatch.setenv(LLM_LOG_PATH_ENV, str(log_path))

        log_llm_call("chat", "gpt-4o", 0.0, object())

        record = json.loads(log_path.read_text(encoding="utf-8"))
        assert record["resolved_model"] is None
        assert "prompt_tokens" not in record

    def test_unwritable_path_does_not_raise(self, monkeypatch, tmp_path):
        monkeypatch.setenv(LLM_LOG_PATH_ENV, str(tmp_path / "no_dir" / "x.jsonl"))
        log_llm_call("chat", "gpt-4o", 0.0, _FakeResponse())  # must not raise


class TestServicesUseSharedConfig:
    def test_llm_agent_uses_pinned_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
        from app.services.llm_agent import LLMAgent

        agent = LLMAgent(api_key="test-key")
        assert agent.model == DEFAULT_MODEL
        assert agent.temperature == DEFAULT_TEMPERATURE

    def test_code_generator_uses_pinned_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
        from app.services.code_generator import MicroscopyCodeGenerator

        generator = MicroscopyCodeGenerator(api_key="test-key")
        assert generator.model == DEFAULT_MODEL
        assert generator.temperature == DEFAULT_TEMPERATURE
