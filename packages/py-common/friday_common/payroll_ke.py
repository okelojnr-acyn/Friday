"""Kenyan statutory payroll deductions (HR plan phase 2): what comes off a
month's gross pay, and what the employer adds on top.

    d = kenya_deductions(10_000_000)          # KES 100,000 gross, in cents
    d.net_cents == 7_196_165                  # 100,000 - 6,000 - 2,750 - 1,500 - 19,308.35

Order (KRA, from December 2024): NSSF, SHIF and the Housing Levy come off
gross first; PAYE is charged on what's left by the monthly bands, less the
personal relief. Rates are data with a start date: when the law changes,
add a row to RATES, don't edit an old one (payslips already made keep
theirs). Sources checked 2026-11-26: NSSF limits from February 2026 (KES
9,000 / 108,000), PAYE bands and relief unchanged by the Finance Act 2026.
Confirm against KRA and NSSF before relying on a new row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Rates:
    starts: date
    # NSSF: 6% each side, Tier I up to the lower limit, Tier II up to the upper.
    nssf_rate: float
    nssf_lower_cents: int
    nssf_upper_cents: int
    # SHIF (Social Health Authority): % of gross, with a monthly minimum.
    shif_rate: float
    shif_min_cents: int
    # Affordable Housing Levy: % of gross, each side.
    levy_rate: float
    # PAYE monthly bands: (upper bound in cents or None, rate).
    bands: tuple[tuple[int | None, float], ...]
    relief_cents: int


_BANDS = ((2_400_000, 0.10), (3_233_300, 0.25), (50_000_000, 0.30), (80_000_000, 0.325), (None, 0.35))

RATES = (
    Rates(date(2025, 2, 1), 0.06, 800_000, 7_200_000, 0.0275, 30_000, 0.015, _BANDS, 240_000),
    Rates(date(2026, 2, 1), 0.06, 900_000, 10_800_000, 0.0275, 30_000, 0.015, _BANDS, 240_000),
)


def rates_on(day: date) -> Rates:
    """The rates in force on `day` (the latest row that has started)."""
    current = [r for r in RATES if r.starts <= day]
    return current[-1] if current else RATES[0]


@dataclass(frozen=True)
class Deductions:
    gross_cents: int
    nssf_cents: int  # employee
    shif_cents: int
    levy_cents: int  # employee
    taxable_cents: int
    paye_cents: int
    net_cents: int
    employer_nssf_cents: int
    employer_levy_cents: int


def _paye(taxable: int, r: Rates) -> int:
    tax, lower = 0.0, 0
    for upper, rate in r.bands:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or taxable <= upper:
            break
        lower = upper
    return max(0, round(tax) - r.relief_cents)


def kenya_deductions(gross_cents: int, on: date | None = None) -> Deductions:
    """One month's deductions on `gross_cents` (KES cents), at the rates in
    force `on` that day (today when not given)."""
    r = rates_on(on or date.today())
    gross = max(0, int(gross_cents))
    tier1 = min(gross, r.nssf_lower_cents)
    tier2 = max(0, min(gross, r.nssf_upper_cents) - r.nssf_lower_cents)
    nssf = round((tier1 + tier2) * r.nssf_rate)
    shif = max(r.shif_min_cents, round(gross * r.shif_rate)) if gross else 0
    levy = round(gross * r.levy_rate)
    taxable = max(0, gross - nssf - shif - levy)
    paye = _paye(taxable, r)
    return Deductions(
        gross_cents=gross,
        nssf_cents=nssf,
        shif_cents=shif,
        levy_cents=levy,
        taxable_cents=taxable,
        paye_cents=paye,
        net_cents=gross - nssf - shif - levy - paye,
        employer_nssf_cents=nssf,
        employer_levy_cents=levy,
    )


def band_tax_cents(taxable_cents: int, on: date | None = None) -> int:
    """Tax on the bands before the personal relief (the P10's "tax charged")."""
    r = rates_on(on or date.today())
    tax, lower = 0.0, 0
    for upper, rate in r.bands:
        top = taxable_cents if upper is None else min(taxable_cents, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or taxable_cents <= upper:
            break
        lower = upper
    return round(tax)


def nssf_tiers(gross_cents: int, on: date | None = None) -> tuple[int, int]:
    """(Tier I, Tier II) employee contribution; the employer pays the same."""
    r = rates_on(on or date.today())
    gross = max(0, int(gross_cents))
    tier1 = min(gross, r.nssf_lower_cents)
    tier2 = max(0, min(gross, r.nssf_upper_cents) - r.nssf_lower_cents)
    return round(tier1 * r.nssf_rate), round(tier2 * r.nssf_rate)
