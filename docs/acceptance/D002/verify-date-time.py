"""Verify the test environment registers and enforces JSON Schema date-time."""

import json

from jsonschema import FormatChecker
from jsonschema.exceptions import FormatError


checker = FormatChecker()
assert "date-time" in checker.checkers, "date-time format checker is not registered"

cases = [
    ("utc_z", "2026-10-13T10:00:00Z", True),
    ("timezone_offset", "2026-10-13T18:00:00+08:00", True),
    ("valid_leap_day", "2028-02-29T00:00:00Z", True),
    ("naive_no_timezone", "2026-10-13T10:00:00", False),
    ("invalid_calendar_day", "2026-02-30T10:00:00Z", False),
    ("invalid_calendar_month", "2026-13-13T10:00:00Z", False),
    ("malformed", "not-a-timestamp", False),
]
results = []
for case, value, expected_valid in cases:
    try:
        checker.check(value, "date-time")
        actual_valid = True
    except FormatError:
        actual_valid = False
    results.append(
        {
            "case": case,
            "value": value,
            "expected_valid": expected_valid,
            "actual_valid": actual_valid,
        }
    )
    assert actual_valid is expected_valid, f"Unexpected date-time validation for {case}"

print(json.dumps({"date_time_registered": True, "cases": results}, ensure_ascii=False))
