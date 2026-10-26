"""Today's date, overridable with DEAL_ENGINE_TODAY=YYYY-MM-DD (the demo simulates several days)."""
import os
from datetime import date


def today():
    v = os.environ.get("DEAL_ENGINE_TODAY")
    return date.fromisoformat(v) if v else date.today()


def today_str():
    return str(today())
