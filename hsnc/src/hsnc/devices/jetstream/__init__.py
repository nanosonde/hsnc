"""JetStream-specific device code (TP-Link managed switches).

Groups everything that is specific to TP-Link JetStream switches in one place:

* :mod:`.adapter` — the SSH/CLI configuration adapter (config plane).
* :mod:`.config_renderer` — renders a device into JetStream CLI commands.
* :mod:`.snmp_monitoring` — runtime polling over SNMPv3 (monitoring plane).
"""
