"""Load-bearing wording of the adjudication schema.

These strings are prompt surface: they become the ``description`` of the structured-output schema
fields the adjudicator reads, and the adjudicator prompt quotes them. They live in the domain
package so the schema never imports from the station that uses it.
"""

from typing import Final

DESC_FINAL: Final = (
    "The final remittance extraction, in the same schema as the two readings. Every value must "
    "be a value that reading A or reading B produced; never write a value neither reader gave."
)
DESC_FIELD_PATH: Final = (
    "The name of a top-level field of the extraction (for example payer_name or "
    "payment_amount). Use the field name exactly as it appears in the readings."
)
DESC_SOURCE_CHOICE: Final = (
    "Where the final value came from: A when taken from reading A, B when taken from reading B, "
    "both when the two readers agree or when the value combines both (the union of list items)."
)
DESC_FIELD_CHOICES: Final = (
    "One entry for every top-level field of the extraction except lines, saying which reading "
    "the final value came from. No field may be left out."
)
DESC_LINE_NO: Final = "The line_no of a line in the final extraction."
DESC_LINE_CHOICES: Final = (
    "One entry for every line in the final extraction, saying which reading the line came from. "
    "Use both for a line that appears in both readings."
)
DESC_DISAGREEMENTS: Final = (
    "One entry for every field or line where the two readings differ, including the ones you "
    "resolved. Leave empty only when the readings agree everywhere."
)
DESC_DISAGREEMENT_PATH: Final = (
    "The field name, or lines[n] with the line_no for a line, where the readings differ."
)
DESC_VALUE_A: Final = "Reading A's value as short JSON text, or null when A gave none."
DESC_VALUE_B: Final = "Reading B's value as short JSON text, or null when B gave none."
DESC_CHOSEN: Final = "Which reading the final value was taken from: A, B or both."
DESC_REASON: Final = (
    "Why this choice, in one short sentence of at most 300 characters. Do not repeat personal data."
)
DESC_DECISION_CONFIDENCE: Final = (
    "Your confidence in the decision as a whole, from 0 to 1. Lower it when the readings "
    "disagree on amounts, invoice numbers or the payer, and when you could not tell which "
    "reading is right."
)
