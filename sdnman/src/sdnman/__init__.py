"""sdn-manager REST backend: device I/O, polling and persistence.

The modules keep a clean dependency direction in a flat layout:
    entities / value_objects / enums / interfaces -> core types and abstract ports
    use_cases (+ dtos, services)                  -> application logic (depend on the core)
    config / devices / persistence                -> concrete adapters (YAML, SQLite, SSH)
    backend                                       -> Flask REST app, runtime and CLI

The composition root in ``container.py`` wires the adapters to the ports. The web
UI lives in the separate ``sdnweb`` package and talks to this backend over HTTP.
"""

__version__ = "0.1.0"
