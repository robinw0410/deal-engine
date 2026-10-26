"""Score hooks for tests. CALLS collects (listing id, info) of every call."""
CALLS = []


def record(listing, info):
    CALLS.append((listing.get("id"), {k: v for k, v in info.items() if k not in ("settings", "locale")}))
    return None
