"""Anonymise the previous build's production day into test fixtures (offline, local only)."""

from cashapp.tools.anonymise.fixture_format import (
    DEFAULT_PRIOR_DIR,
    FORMAT_VERSION,
    LABEL_EXPECTATIONS,
    ExpectedDecision,
    LabelExpectation,
    LineLabel,
    OutcomeLine,
    PriorFailure,
    PriorFixtures,
    PriorLabel,
    PriorManifest,
    PriorMessage,
    PriorOutcome,
    expected_for,
    load_labelled,
    load_manifest,
    load_prior_day,
)
from cashapp.tools.anonymise.scan import (
    ANONYMISED_MARKERS,
    Finding,
    FindingKind,
    load_denylist,
    scan_for_identifiers,
    scan_paths,
)
from cashapp.tools.anonymise.source import SourceBundle, load_source
from cashapp.tools.anonymise.synthetic import write_synthetic_source
from cashapp.tools.anonymise.transform import anonymise

__all__ = [
    "ANONYMISED_MARKERS",
    "DEFAULT_PRIOR_DIR",
    "FORMAT_VERSION",
    "LABEL_EXPECTATIONS",
    "ExpectedDecision",
    "Finding",
    "FindingKind",
    "LabelExpectation",
    "LineLabel",
    "OutcomeLine",
    "PriorFailure",
    "PriorFixtures",
    "PriorLabel",
    "PriorManifest",
    "PriorMessage",
    "PriorOutcome",
    "SourceBundle",
    "anonymise",
    "expected_for",
    "load_denylist",
    "load_labelled",
    "load_manifest",
    "load_prior_day",
    "load_source",
    "scan_for_identifiers",
    "scan_paths",
    "write_synthetic_source",
]
