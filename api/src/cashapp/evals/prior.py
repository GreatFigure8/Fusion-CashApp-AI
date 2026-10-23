"""The anonymised prior-build fixtures, read through s43's loaders (one format, one reader)."""

from pathlib import Path

from pydantic import ValidationError

from cashapp.tools.anonymise.fixture_format import (
    PriorFixtures,
    load_labelled,
    load_manifest,
    load_prior_day,
)

__all__ = ["PriorUnavailable", "load_prior"]


class PriorUnavailable(Exception):  # noqa: N818 - reads as a condition, not an error class
    """The fixtures directory is missing or does not follow s43's format."""


def load_prior(directory: Path) -> PriorFixtures:
    """Messages, the fake-Fusion document, AR's labelled failures and the manifest."""
    try:
        messages, fusion = load_prior_day(directory)
        failures = load_labelled(directory)
        manifest = load_manifest(directory)
    except (OSError, ValueError, ValidationError) as exc:
        # Never echo the exception text: validation messages can quote fixture values.
        raise PriorUnavailable(
            f"prior fixtures at {directory} could not be read ({type(exc).__name__})"
        ) from None
    return PriorFixtures(messages=messages, fusion=fusion, failures=failures, manifest=manifest)
