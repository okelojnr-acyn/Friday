"""Kenyan deductions, checked against worked examples (2026 rates)."""

from datetime import date

from friday_common.payroll_ke import kenya_deductions

FEB_2026 = date(2026, 3, 1)


def test_100k_gross_matches_the_worked_example():
    d = kenya_deductions(10_000_000, FEB_2026)
    assert (d.nssf_cents, d.shif_cents, d.levy_cents) == (600_000, 275_000, 150_000)
    assert d.taxable_cents == 8_975_000
    assert d.paye_cents == 1_930_835  # 21,708.35 on the bands - 2,400 relief
    assert d.net_cents == 10_000_000 - 600_000 - 275_000 - 150_000 - 1_930_835
    assert (d.employer_nssf_cents, d.employer_levy_cents) == (600_000, 150_000)


def test_nssf_is_capped_at_the_upper_limit_and_rose_in_february_2026():
    assert kenya_deductions(50_000_000, FEB_2026).nssf_cents == 648_000  # 6% of 108,000
    assert kenya_deductions(50_000_000, date(2026, 1, 15)).nssf_cents == 432_000  # 6% of 72,000 before


def test_low_pay_pays_no_paye_and_the_shif_minimum():
    d = kenya_deductions(1_000_000, FEB_2026)  # KES 10,000
    assert d.shif_cents == 30_000  # the KES 300 minimum, not 2.75% (275)
    assert d.paye_cents == 0  # relief exceeds the tax
    assert d.net_cents == 1_000_000 - d.nssf_cents - 30_000 - d.levy_cents


def test_top_band():
    d = kenya_deductions(100_000_000, FEB_2026)  # KES 1,000,000
    assert d.paye_cents > 0 and d.net_cents < 100_000_000
    # Every shilling above 800,000 of taxable pay is taxed at 35%.
    more = kenya_deductions(100_100_000, FEB_2026)
    assert abs((more.paye_cents - d.paye_cents) - round((more.taxable_cents - d.taxable_cents) * 0.35)) <= 1
