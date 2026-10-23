"""Parameterised Fusion test-data generator (non-production pods only)."""

from cashapp.tools.testdata.cleanup import cleanup, load_manifests, render_cleanup_steps
from cashapp.tools.testdata.fixtures import (
    FixturePaths,
    plan_to_fake_json,
    render_remittance_csv,
    write_fixtures,
    write_manifest,
)
from cashapp.tools.testdata.generator import GenerationError, generate
from cashapp.tools.testdata.models import (
    CleanupReport,
    CreatedRecord,
    Expected,
    ExpectedLine,
    GeneratedData,
    PlannedApplication,
    PlannedReceipt,
    PlannedTransaction,
    ScenarioName,
    ScenarioParams,
    ScenarioPlan,
    TaggedRecord,
)
from cashapp.tools.testdata.safety import (
    ProductionPodRefused,
    assert_non_production,
    production_hosts,
)
from cashapp.tools.testdata.scenarios import PRESETS, Scenario, build_plan
from cashapp.tools.testdata.tagging import (
    TAG_PATTERN,
    is_tagged,
    tag_marker,
    tagged_number,
    validate_tag,
)

__all__ = [
    "PRESETS",
    "TAG_PATTERN",
    "CleanupReport",
    "CreatedRecord",
    "Expected",
    "ExpectedLine",
    "FixturePaths",
    "GeneratedData",
    "GenerationError",
    "PlannedApplication",
    "PlannedReceipt",
    "PlannedTransaction",
    "ProductionPodRefused",
    "Scenario",
    "ScenarioName",
    "ScenarioParams",
    "ScenarioPlan",
    "TaggedRecord",
    "assert_non_production",
    "build_plan",
    "cleanup",
    "generate",
    "is_tagged",
    "load_manifests",
    "plan_to_fake_json",
    "production_hosts",
    "render_cleanup_steps",
    "render_remittance_csv",
    "tag_marker",
    "tagged_number",
    "validate_tag",
    "write_fixtures",
    "write_manifest",
]
