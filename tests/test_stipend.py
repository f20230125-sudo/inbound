import pytest

from inbound.extract.stipend import parse_stipend


@pytest.mark.parametrize(
    "raw,currency,lo,hi,period",
    [
        ("· AED2500 per month", "AED", 2500, 2500, "month"),
        ("· AED 2,000 per month", "AED", 2000, 2000, "month"),
        ("· AED2000/- per month", "AED", 2000, 2000, "month"),
        ("· between INR 10,000 to 15,000 per month.", "INR", 10000, 15000, "month"),
        ("INR 500 per day", "INR", 500, 500, "day"),
    ],
)
def test_stipend(raw, currency, lo, hi, period):
    field = parse_stipend(raw)
    assert field["normalized"] == {"currency": currency, "min": lo, "max": hi, "period": period}
    assert field["raw"] == raw
    assert field["status"] == "found"


@pytest.mark.parametrize("raw", ["", "· As per company norms"])
def test_unknown(raw):
    field = parse_stipend(raw)
    assert field["normalized"] is None and field["status"] == "unknown"
    assert field["source_text"] == raw
