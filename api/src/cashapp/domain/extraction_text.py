"""Load-bearing wording of the extraction schema.

These strings are prompt surface: they become the ``description`` of the schema fields (so the
model reads them as part of the structured-output schema) and are quoted by the reader prompt.
They live in the domain package so the schema never imports from the station that uses it.
"""

from typing import Final

DESC_VALUE: Final = (
    "The value exactly as it appears on the remittance, normalised only to the declared type. "
    "null when the remittance does not state it. Never infer, calculate or guess a value."
)
DESC_SOURCE: Final = (
    "Where the value was read: the part number, the page and the region. "
    "null when the value was not found, so it has no location."
)
DESC_CONFIDENCE: Final = (
    "Your own confidence in this value from 0 to 1. Use a low number when the text is blurred, "
    "ambiguous or cut off, and 0 when the value is null."
)
DESC_PART_NO: Final = (
    "The number of the artifact part, counting from 1 in the order the parts were supplied."
)
DESC_PAGE: Final = "The 1-based page within the part, or null for parts that have no pages."
DESC_BBOX: Final = (
    "The region of the page holding the value, as fractions of the page width and height "
    "(x, y of the top-left corner, w, h of the box), each from 0 to 1. null when unknown."
)
DESC_QUOTE: Final = "The short text read at that location, at most 300 characters. null if none."

DESC_PAYER_NAME: Final = (
    "The name of the party that made the payment, as written on the remittance (the remitter, "
    "not the payee that receives the money)."
)
DESC_PAYER_BANK_ACCOUNT: Final = (
    "The payer's bank account or IBAN as printed, if any. Keep it exactly as shown, as a string."
)
DESC_REMITTANCE_REFERENCE: Final = (
    "The payer's own reference for this payment: remittance advice number, payment number, "
    "check or EFT number, or the document title reference. A string."
)
DESC_PAYMENT_AMOUNT: Final = (
    "The total amount of the payment as a decimal string with two decimals, for example "
    "'12480.00'. Never a number type, never with a currency symbol or thousands separator."
)
DESC_CURRENCY_RAW: Final = (
    "The currency exactly as written (for example 'USD', 'US$', '$', 'EUR', 'Rs.'). "
    "Do not convert it."
)
DESC_CURRENCY: Final = (
    "The ISO 4217 code (three capital letters) only when the remittance makes it certain. "
    "A bare '$' is not certain: leave the value null for it."
)
DESC_CURRENCY_AMBIGUOUS: Final = (
    "true when the currency is written with a bare '$' or any other symbol that fits more than "
    "one currency and nothing else on the document settles it."
)
DESC_DATES: Final = (
    "Every date on the remittance that could matter, each with its kind: payment (the date the "
    "money was or will be paid), issue (the remittance or document date), order, deposit, or "
    "other. Keep all of them, even when they differ."
)
DESC_DATE_VALUE: Final = "The date in ISO form, YYYY-MM-DD. Resolve day/month order from context."
DESC_DATE_KIND: Final = "payment, issue, order, deposit or other."
DESC_PAYMENT_DATE: Final = (
    "The one date you judge to be the payment date, chosen from the dates you listed. "
    "null when no date can be justified as the payment date."
)
DESC_LINES: Final = (
    "One entry per line of the remittance, in the order printed: invoices, credit memos, bank "
    "fees, tariffs and discount lines. Include a line even when it states no amount."
)
DESC_LINE_NO: Final = "The position of the line on the remittance, counting from 1."
DESC_LINE_KIND: Final = (
    "INVOICE, CREDIT_MEMO (also for returns and negative documents), BANK_FEE, TARIFF, DISCOUNT, "
    "or UNKNOWN when the type cannot be told."
)
DESC_TRANSACTION_NUMBER: Final = (
    "The invoice or credit memo number as a string, character for character: keep leading "
    "zeros, letters, and suffixes such as '-1'. Never a JSON number. Use an empty string only "
    "for BANK_FEE, TARIFF and DISCOUNT lines that have no document number."
)
DESC_AMOUNT_PAID: Final = (
    "The amount the payer says they paid against this line, as a decimal string with two "
    "decimals; negative for credit memos. null when the line states no paid amount."
)
DESC_GROSS_AMOUNT: Final = (
    "The original or gross amount of the document on the line, as a decimal string. null if absent."
)
DESC_DISCOUNT_CLAIMED: Final = (
    "A discount the payer claims on this line, as a positive decimal string. null if none is "
    "stated. Never work out a discount that is not written."
)
DESC_DEDUCTION: Final = (
    "An amount the payer deducted from this line (short pay, dispute, tax withholding), as a "
    "positive decimal string. null if none is stated."
)
DESC_PO_NUMBER: Final = "A purchase order number on this line, as a string. null if none."
DESC_SALES_ORDER: Final = "A sales order number on this line, as a string. null if none."
DESC_ERS_REFERENCE: Final = (
    "An evaluated receipt settlement (ERS) reference on this line. null if none."
)
DESC_PO_REFS: Final = "Every purchase order number on the remittance, as strings."
DESC_SALES_ORDER_REFS: Final = "Every sales order number on the remittance, as strings."
DESC_ERS_REFS: Final = "Every evaluated receipt settlement (ERS) reference on the remittance."
DESC_BANK_FEES: Final = (
    "Bank charges or fees deducted from the payment, each with its amount and the currency "
    "code. Empty when none are stated."
)
DESC_NOTES: Final = (
    "Anything else useful for matching that does not fit a field above (for example "
    "'prepayment', 'partial payment', 'two currencies'). Never put personal data here. null if "
    "nothing."
)
