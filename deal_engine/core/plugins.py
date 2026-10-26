"""Loading extension code by name.

A plugin is given as "module:attribute" (e.g. "my_adapters.shop:ShopAdapter" or
"my_hooks:second_look"). The module must be importable: installed, or in a directory listed
under plugin_paths in the config (relative to the config file).
"""
import importlib
import importlib.metadata

from .config import ConfigError


def load(spec, what="plugin"):
    mod, sep, attr = str(spec).partition(":")
    if not sep or not mod or not attr:
        raise ConfigError(f"{what} '{spec}' must be given as 'module:attribute'")
    try:
        m = importlib.import_module(mod)
    except Exception as e:   # ImportError, SyntaxError, errors at import time of the plugin
        raise ConfigError(f"{what} '{spec}': module '{mod}' cannot be imported ({type(e).__name__}: {e})")
    obj = m
    for part in attr.split("."):
        if not hasattr(obj, part):
            raise ConfigError(f"{what} '{spec}': '{attr}' not found in module '{mod}'")
        obj = getattr(obj, part)
    return obj


def entry_points(group):
    """{name: EntryPoint} of installed packages for an entry point group."""
    try:
        eps = importlib.metadata.entry_points()
        found = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])
    except Exception:   # broken package metadata must not break a run
        return {}
    return {ep.name: ep for ep in found}
