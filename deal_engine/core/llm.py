"""Calls to an LLM through the Claude Code CLI in print mode ("claude -p").

The evaluation and prefilter steps need an agent that can read files (candidate batches,
downloaded photos) and write one JSON result file, which is why this uses the CLI with the
Read/Write tools instead of a plain API call. The command and extra arguments are configurable
(llm.command, llm.extra_args).

Every call gets --tools with an explicit list (Read/Write, or none for classification) and
--disallowedTools Bash WebFetch WebSearch. llm.extra_args cannot re-enable these tools.
"""
import re
import subprocess

from . import config as config_mod
from . import locale as locale_mod
from .config import ConfigError

DISALLOWED = ("Bash", "WebFetch", "WebSearch")
_ALLOW_FLAGS = ("--tools", "--allowedTools", "--allowed-tools")


def fill(template, **values):
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def prompt(cfg, sc, name, **values):
    """Prompt text for an LLM step (evaluate, prefilter, classify) from the configured file
    (prompts.<name> in the search or globally) or the built-in one for the locale.
    {{WANTED_ADS}} becomes the locale's rule for the search's wanted_ads setting."""
    loc = locale_mod.for_search(cfg, sc)
    wanted = (sc or {}).get("wanted_ads", "reject")
    text = config_mod.prompt_path(cfg, sc, name).read_text()
    return fill(text, WANTED_ADS=loc.t(f"wanted.{wanted}"), **values)


def check_extra_args(args):
    """Raise ConfigError if llm.extra_args try to allow Bash, WebFetch or WebSearch
    (--tools/--allowedTools/--allowed-tools, also as --flag=value)."""
    flag = None
    for a in (str(x) for x in args):
        if a.startswith("-"):
            name, _, val = a.partition("=")
            flag = name if name in _ALLOW_FLAGS else None
            if not (flag and val):
                continue
            a = val
        if flag and re.search(r"\b(" + "|".join(DISALLOWED) + r")\b", a, re.I):
            raise ConfigError(f"llm.extra_args: {flag} must not allow {', '.join(DISALLOWED)} (got {a!r})")


def run(cfg, text, model, tools=("Read", "Write"), max_turns=30, timeout_min=None, cwd=None, log_file=None):
    """Run one prompt. Returns stdout; raises RuntimeError on a non-zero exit or timeout."""
    lc = cfg.get("llm") or {}
    cmd = list(lc.get("command") or ["claude", "-p"]) + ["--model", model, "--max-turns", str(max_turns)]
    # --tools limits which tools exist at all, --allowedTools pre-approves them (no prompts in -p mode)
    cmd += ["--tools", *(tools or [""])]
    if tools:
        cmd += ["--allowedTools", *tools]
    extra = [str(a) for a in lc.get("extra_args") or []]
    check_extra_args(extra)
    cmd += extra
    # always last, whatever extra_args say: these tools never run, even if allowed elsewhere
    cmd += ["--disallowedTools", *DISALLOWED]
    timeout = 60 * float(timeout_min or lc.get("timeout_minutes", 60))
    try:
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"LLM call timed out after {timeout / 60:.0f} min")
    except FileNotFoundError:
        raise RuntimeError(f"LLM command not found: {cmd[0]}")
    if log_file:
        with open(log_file, "a") as f:
            f.write(r.stdout + r.stderr)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-300:])
    return r.stdout
