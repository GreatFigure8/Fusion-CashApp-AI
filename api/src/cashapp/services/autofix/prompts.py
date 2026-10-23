"""Prompt surface for the escalation summary: the system prompt and the field description."""

from typing import Final

PROMPT_VERSION: Final = "1"
SUMMARY_MAX_TOKENS: Final = 400
SUMMARY_TIMEOUT_CAP_S: Final = 20.0

DESC_SUMMARY: Final = (
    "At most three short sentences in plain language that tell an accounts receivable clerk "
    "why this payment is stuck and what they should check or decide next. Use only the facts "
    "given. Do not invent invoice numbers, amounts or customer names."
)

SUMMARY_SYSTEM_PROMPT: Final = (
    "You help accounts receivable staff with cash application. A remittance could not be "
    "applied automatically and automatic fixes did not resolve it. You receive a JSON block of "
    "facts about the stuck item: the stage, the error, what was already tried and a few header "
    "values.\n"
    "Write a summary of at most three sentences in plain language: what went wrong, what the "
    "system already tried, and what the person should check or decide next.\n"
    "Rules: use only the facts in the JSON; never invent numbers, names or reasons; do not "
    "give financial advice; do not repeat the JSON."
)
