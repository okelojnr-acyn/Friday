"""KRA PIN format: A (individual) or P (non-individual), nine digits, a
check letter. e.g. P051234567X."""

import re

_PIN = re.compile(r"^[AP][0-9]{9}[A-Z]$")


def normalize_pin(raw: str | None) -> str:
    return (raw or "").strip().upper().replace(" ", "")


def is_kra_pin(raw: str | None) -> bool:
    return bool(_PIN.match(normalize_pin(raw)))
