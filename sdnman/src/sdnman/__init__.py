"""sdn-manager: self-hosted network controller UI.

Clean Architecture layout:
    domain          -> enterprise entities, value objects, abstract interfaces (no deps)
    application     -> use cases / DTOs (depends only on domain)
    infrastructure  -> concrete adapters: YAML config, SQLite, device drivers
    presentation    -> Flask web UI + CLI (composition happens here)
"""

__version__ = "0.1.0"
