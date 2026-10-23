"""The classify decision: is this artifact remittance advice?

The wording of the field descriptions and of the remittance definition is prompt surface. It
lives here once; the field descriptions and ``stations/classify/prompts.py`` both import it.
"""

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

CLASSIFICATION_SCHEMA_VERSION: Final = "1"
REASON_MAX_CHARS: Final = 300

REMITTANCE_DEFINITION: Final = (
    "Remittance advice is a payer's notice that a payment was or will be made to us, identifying "
    "what it pays: invoice or credit memo numbers, amounts, a payment reference or a payment "
    "date. Remittance emails, ACH, EFT and wire advices, check stubs, payment-run spreadsheets "
    "and portal payment notifications are remittance advice, and so is a forwarded remittance. "
    "Invoices or statements with no payment, dunning or reminder notices, purchase orders, "
    "quotes, newsletters, auto-replies, bodies that hold only a signature and bank statements "
    "with no per-invoice detail are not."
)

DESC_IS_REMITTANCE: Final = "True when the artifact is remittance advice. " + REMITTANCE_DEFINITION
DESC_REASON: Final = (
    "One or two sentences naming the evidence for the decision (for example, that it lists "
    f"invoice numbers and amounts paid). At most {REASON_MAX_CHARS} characters. Do not copy "
    "account numbers."
)
DESC_CONFIDENCE: Final = "Your probability, from 0 to 1, that the decision is correct."


class ClassificationOrigin(StrEnum):
    MODEL = "MODEL"
    HUMAN = "HUMAN"


class ClassificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    is_remittance: bool = Field(description=DESC_IS_REMITTANCE)
    reason: str = Field(min_length=1, max_length=REASON_MAX_CHARS, description=DESC_REASON)
    confidence: float = Field(ge=0.0, le=1.0, description=DESC_CONFIDENCE)
