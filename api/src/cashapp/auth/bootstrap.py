"""The identity-domain group that migration 0002 maps to ADMIN so the first sign-in works."""

from typing import Final

BOOTSTRAP_ADMIN_GROUP: Final = "CashApp-Admins"
"""Fixed: it is only read by that one migration. Group-to-role mapping is edited in Settings."""
