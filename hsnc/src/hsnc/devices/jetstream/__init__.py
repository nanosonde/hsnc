"""JetStream-specific device code (TP-Link managed switches).

Groups everything that is specific to TP-Link JetStream switches in one place:

* :mod:`.adapter` — the SSH/CLI configuration adapter (primary connection).
* :mod:`.config_renderer` — renders a device into JetStream CLI commands.
* :mod:`.ssh_monitoring` — primary runtime polling over the SSH CLI.
* :mod:`.snmp_monitoring` — secondary runtime polling over SNMPv3.
"""
