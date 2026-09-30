from __future__ import annotations

import hashlib
import re

# Applied in order. Email goes first so digits inside an address are not
# half-redacted by phone_vn; longer digit runs (card > CCCD > phone) go before shorter ones.
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    # 13–19 digit PAN, optionally grouped with spaces/dashes (Visa/Master 16, Amex 15, ...).
    "credit_card": r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)",
    "cccd": r"(?<!\d)\d{12}(?!\d)",
    # 0xx / +84 / 84 followed by 9 digits, with optional space, dot or dash separators.
    "phone_vn": r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){9}(?!\d)",
    # Vietnamese passport: one uppercase letter + 7 digits, e.g. C1234567.
    "passport": r"\b[A-Z]\d{7}\b",
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = re.sub(pattern, f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
