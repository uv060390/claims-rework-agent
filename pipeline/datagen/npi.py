"""Synthetic NPI generation with valid Luhn check digits.

Real NPIs validate via the Luhn algorithm over the 15-digit string formed by
prefixing '80840' to the first 9 digits; the 10th digit is the check digit.
Generated NPIs are structurally valid but random — they are not real providers.
"""

import random

_PREFIX = "80840"


def _luhn_check_digit(partial: str) -> int:
    total = 0
    for i, ch in enumerate(reversed(partial)):
        d = int(ch)
        if i % 2 == 0:  # rightmost digit of the partial gets doubled
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def make_npi(rng: random.Random) -> str:
    """Generate a structurally valid 10-digit NPI (starts with 1 or 2)."""
    first9 = str(rng.choice([1, 2])) + "".join(str(rng.randint(0, 9)) for _ in range(8))
    return first9 + str(_luhn_check_digit(_PREFIX + first9))


def is_valid_npi(npi: str) -> bool:
    if len(npi) != 10 or not npi.isdigit() or npi[0] not in "12":
        return False
    return int(npi[9]) == _luhn_check_digit(_PREFIX + npi[:9])
