"""Shared OpenAI model and decoding configuration, plus a per-call audit log.

Single source of truth for the model identifier and sampling temperature used
by llm_agent.py and code_generator.py. The manuscript pins the exact snapshot
below; keeping it in one place means the code, README, and paper cannot drift
apart independently (there is a test asserting the README matches).
"""

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Exact snapshot used for the experiments reported in the manuscript. Override
# with OPENAI_MODEL; the resolved snapshot OpenAI actually serves is recorded
# per call by log_llm_call().
DEFAULT_MODEL = "gpt-4o-2024-08-06"

# Deterministic-as-possible decoding by default; override with
# OPENAI_TEMPERATURE (0-2).
DEFAULT_TEMPERATURE = 0.0

LLM_LOG_PATH_ENV = "GRIDSCOPE_LLM_LOG"
DEFAULT_LLM_LOG_PATH = "llm_calls.jsonl"


def get_model() -> str:
    """Return the model to request, honouring the OPENAI_MODEL override."""
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def get_temperature() -> float:
    """Return the sampling temperature, honouring OPENAI_TEMPERATURE.

    Raises:
        ValueError: if OPENAI_TEMPERATURE is set but is not a number in [0, 2].
    """
    raw = os.getenv("OPENAI_TEMPERATURE")
    if raw is None or raw.strip() == "":
        return DEFAULT_TEMPERATURE
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"OPENAI_TEMPERATURE must be a number between 0 and 2, got {raw!r}"
        ) from None
    if not 0.0 <= value <= 2.0:
        raise ValueError(
            f"OPENAI_TEMPERATURE must be between 0 and 2, got {value}"
        )
    return value


def log_llm_call(
    purpose: str,
    requested_model: str,
    temperature: float,
    response: Any,
) -> None:
    """Append one JSONL record for an OpenAI chat-completion call.

    ``response.model`` is the snapshot OpenAI actually served (e.g.
    ``gpt-4o-2024-08-06`` even when the floating ``gpt-4o`` alias was
    requested) — recording it is what makes this log a reproducibility
    record. Never raises: a failed log write must not fail the user request.
    """
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": purpose,
        "requested_model": requested_model,
        "resolved_model": getattr(response, "model", None),
        "temperature": temperature,
    }
    usage = getattr(response, "usage", None)
    if usage is not None:
        record["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
        record["completion_tokens"] = getattr(usage, "completion_tokens", None)

    path = os.getenv(LLM_LOG_PATH_ENV, DEFAULT_LLM_LOG_PATH)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("Could not write LLM call log to %s: %s", path, exc)
