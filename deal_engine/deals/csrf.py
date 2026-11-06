"""CSRF protection of the deal server (write requests of the wish list; origin check for all writes).

The deal server has no users: authentication is done by the web server in front of it (cookie or
basic auth). The browser sends those credentials with requests from other sites too, so every
write request needs proof that it comes from our own page:

* token: "<unix time>.<HMAC-SHA256(secret, 'deals-csrf:' + time)>", embedded in our forms (hidden
  field `csrf`) and returned by GET /api/wishes (send it back as header X-CSRF-Token). Valid for
  MAX_AGE seconds; compared with hmac.compare_digest. Another site cannot read it (same-origin policy).
* secret: 32 random bytes, created on first use in state/deals-secret (mode 0400, symlinks not followed) of the data
  directory; never in code or config. Deleting the file invalidates all tokens.
* origin: `same_origin(headers)` rejects requests a browser marks as cross-site (Sec-Fetch-Site other
  than same-origin) and, for browsers without Sec-Fetch-*, an Origin / Referer whose host is not the
  Host of the request (without port; X-Forwarded-Host only if trusted). Requests without these
  headers (non-browser clients) pass.
"""
import hashlib
import hmac
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

MAX_AGE = 24 * 3600   # a form left open longer must be reloaded
SKEW = 300            # tolerated clock difference for tokens "from the future"
_LOCK = threading.Lock()
_CACHE = {}


def secret_path(cfg):
    return cfg["_data"] / "state" / "deals-secret"


def secret(cfg):
    """The server secret (bytes); created read-only (0400) on first use, so a process without a shell
    (e.g. an LLM evaluator with a file-write tool running as the same user) cannot overwrite it.
    Symlinks are not followed."""
    p = secret_path(cfg)
    key = str(p)
    with _LOCK:
        if key in _CACHE and p.exists():
            return _CACHE[key]
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        except FileExistsError:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as f:
                if os.fstat(f.fileno()).st_mode & 0o277:
                    os.fchmod(f.fileno(), 0o400)
                value = bytes.fromhex(f.read().strip())
            if len(value) < 32:
                raise RuntimeError(f"{p}: secret too short; delete the file to create a new one")
        else:
            value = secrets.token_bytes(32)
            with os.fdopen(fd, "w") as f:
                f.write(value.hex() + "\n")
        _CACHE[key] = value
        return value


def _mac(cfg, ts):
    return hmac.new(secret(cfg), f"deals-csrf:{ts}".encode(), hashlib.sha256).hexdigest()


def token(cfg, now=None):
    ts = int(time.time() if now is None else now)
    return f"{ts}.{_mac(cfg, ts)}"


def valid(cfg, tok, now=None):
    if not isinstance(tok, str) or len(tok) > 100 or tok.count(".") != 1:
        return False
    ts, mac = tok.split(".")
    if not ts.isdigit() or len(ts) > 12:
        return False
    age = int(time.time() if now is None else now) - int(ts)
    if not -SKEW <= age <= MAX_AGE:
        return False
    return hmac.compare_digest(_mac(cfg, int(ts)).encode(), mac.encode())


def _host(h):
    """Host name without port, lower case ("Example.org:8080" -> "example.org")."""
    h = (h or "").strip().lower()
    try:
        return urlsplit("//" + h).hostname or ""
    except ValueError:
        return ""


def same_origin(headers, trust_forwarded_host=False):
    """False for a request a browser sent from another site (see module docstring). Without
    Sec-Fetch-Site the host of Origin (or Referer) must match Host, compared without port (a proxy
    often drops it). X-Forwarded-Host counts only with trust_forwarded_host (deals.trust_forwarded_host),
    because a proxy that does not set it passes a client's value through."""
    site = headers.get("Sec-Fetch-Site")
    if site is not None:
        return site.strip().lower() == "same-origin"
    hosts = {_host(headers.get("Host"))}
    if trust_forwarded_host:
        hosts |= {_host(x) for x in (headers.get("X-Forwarded-Host") or "").split(",")}
    hosts.discard("")
    origin = headers.get("Origin")
    if origin is not None:
        if origin.strip() == "null":
            return False
        return _host(urlsplit(origin.strip()).netloc) in hosts
    ref = headers.get("Referer")
    if ref:
        return _host(urlsplit(ref.strip()).netloc) in hosts
    return True
