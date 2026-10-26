"""Calls to an LLM through the Claude Code CLI in print mode ("claude -p").

The evaluation and prefilter steps need an agent that can read files (candidate batches,
downloaded photos) and write one JSON result file, which is why this uses the CLI with the
Read/Write tools instead of a plain API call. The command and extra arguments are configurable
(llm.command, llm.extra_args).
"""
import subprocess
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"


def fill(template, **values):
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def prompt(name, **values):
    return fill((PROMPTS / f"{name}.md").read_text(), **values)


def run(cfg, text, model, tools=("Read", "Write"), max_turns=30, timeout_min=None, cwd=None, log_file=None):
    """Run one prompt. Returns stdout; raises RuntimeError on a non-zero exit or timeout."""
    lc = cfg.get("llm") or {}
    cmd = list(lc.get("command") or ["claude", "-p"]) + ["--model", model, "--max-turns", str(max_turns)]
    # --tools limits which tools exist at all, --allowedTools pre-approves them (no prompts in -p mode)
    cmd += ["--tools", *(tools or [""])]
    if tools:
        cmd += ["--allowedTools", *tools]
    cmd += [str(a) for a in lc.get("extra_args") or []]
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
