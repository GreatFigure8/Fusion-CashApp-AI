"""Read-only study of which receipt attributes link a remittance to its receipt (spike #12)."""

from cashapp.tools.receipt_signal_study.models import SIGNALS, StudyResult
from cashapp.tools.receipt_signal_study.run import run_study

# The soft signals s13's scorer weighs (hard filters carry no weight). The proposal in
# docs/spikes/receipt-signals.md is keyed by exactly these names.
PROPOSED_SCORER_WEIGHT_KEYS: tuple[str, ...] = (
    "remittance_reference",
    "statement_reference",
    "invoice_set_overlap",
    "payer_bank_account",
    "date_distance",
    "alias_reference_pattern",
    "customer_history",
)

__all__ = ["PROPOSED_SCORER_WEIGHT_KEYS", "SIGNALS", "StudyResult", "run_study"]
