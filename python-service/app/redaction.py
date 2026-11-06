"""PII redaction applied to model output before it is logged (same rules as the Node wrapper)."""

import re

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

REDACTED = "[REDACTED]"


def redact_pii(text: str) -> str:
    """Replace emails, phone numbers and card-like digit runs with [REDACTED]."""
    if not text:
        return text
    # Cards first: a 16-digit card number would otherwise be partly eaten by the phone pattern.
    text = _CARD.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return _PHONE.sub(REDACTED, text)
