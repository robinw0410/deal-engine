import pytest

from deal_engine.core.score import DEFAULTS, fraud


@pytest.mark.parametrize("issues,expected", [
    ("No signs of fraud.", False),
    ("not a scam, seller has many ratings", False),
    ("without prepayment, pickup possible", False),
    ("no stock photo, own pictures", False),
    ("Seller wants prepayment by bank transfer.", True),
    ("Looks like a scam.", True),
    ("Suspiciously cheap for 'brand new'.", True),
    ("Photos are a stock photo.", True),
    # negation applies only to the indicator right after it
    ("No prepayment needed, but the photos look fake.", True),
    ("", False),
])
def test_fraud_negation(issues, expected):
    assert fraud({"issues": issues}, DEFAULTS) is expected


def test_fraud_reads_summary_too():
    assert fraud({"summary": "Probably fake listing"}, DEFAULTS) is True
