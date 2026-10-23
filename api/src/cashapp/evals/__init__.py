"""Evaluation harness: measure model and rule changes against the gold set and prior fixtures.

Run deliberately (``uv run python -m cashapp.evals run --suite all --replay``); never from CI.
"""

from cashapp.evals.models import EvalReport
from cashapp.evals.options import EvalOptions
from cashapp.evals.runner import run_evals

__all__ = ["EvalOptions", "EvalReport", "run_evals"]
