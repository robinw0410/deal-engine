"""Adapter registry.

Where an adapter name comes from, in this order:
  1. the config:      adapters: {shop: "my_package.shop:ShopAdapter"}
  2. an entry point:  [project.entry-points."deal_engine.adapters"] shop = "my_package.shop:ShopAdapter"
  3. built in:        json_file, ebay
There is no fallback: an unknown name or an adapter that cannot run with the given configuration
(e.g. eBay without credentials) raises ConfigError, and the run reports it as failed.
"""
from ..core import plugins
from ..core.config import ConfigError
from .base import Adapter, Blocked  # noqa: F401

GROUP = "deal_engine.adapters"
BUILTIN = {"json_file": "deal_engine.adapters.json_file:JsonFileAdapter",
           "ebay": "deal_engine.adapters.ebay:EbayAdapter"}


def available(cfg=None):
    """{name: where it comes from} for all adapters this config can use."""
    out = {n: "built in" for n in BUILTIN}
    out.update({n: f"entry point {ep.value}" for n, ep in plugins.entry_points(GROUP).items()})
    out.update({n: f"config {spec}" for n, spec in ((cfg or {}).get("adapters") or {}).items()})
    return out


def adapter_class(name, cfg=None):
    spec = ((cfg or {}).get("adapters") or {}).get(name)
    if spec:
        cls = plugins.load(spec, f"adapter '{name}'")
    else:
        ep = plugins.entry_points(GROUP).get(name)
        if ep is not None:
            try:
                cls = ep.load()
            except Exception as e:
                raise ConfigError(f"adapter '{name}' (entry point {ep.value}) cannot be loaded: {e}")
        elif name in BUILTIN:
            cls = plugins.load(BUILTIN[name])
        else:
            raise ConfigError(f"unknown adapter '{name}' (available: {', '.join(sorted(available(cfg)))})")
    if not (isinstance(cls, type) and issubclass(cls, Adapter)):
        raise ConfigError(f"adapter '{name}' must be a subclass of deal_engine.adapters.base.Adapter")
    return cls


def create(name, cfg, sc):
    cls = adapter_class(name, cfg)
    if cls.name != name:   # registered under another name: state ids and settings use the registered name
        cls = type(cls.__name__, (cls,), {"name": name})
    return cls(cfg, sc)
