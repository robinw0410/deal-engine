"""Score hooks for tests. CALLS collects (listing id, info) of every call."""
CALLS = []


def record(listing, info):
    CALLS.append((listing.get("id"), {k: v for k, v in info.items() if k not in ("settings", "locale")}))
    return None


# selection hooks (category_hook / priority_hook, v0.2.11)
def first_word(listing):
    """Category = first word of the title in lower case, None for titles starting with '?'."""
    t = str(listing.get("title") or "")
    return None if t.startswith("?") else t.split()[0].lower()


def starred(listing):
    """Priority 1 for titles containing '*'."""
    return 1 if "*" in str(listing.get("title") or "") else 0


def broken(listing):
    raise ValueError("boom")


NOT_CALLABLE = 42
