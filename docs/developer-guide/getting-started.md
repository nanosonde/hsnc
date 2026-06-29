# Local development setup

Both packages install into one virtualenv.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e "./hsnc[dev,ssh]" -e "./hsncweb[dev]"   # add ,snmp for SNMP work
```

## Run

```bash
hsnc-ctl api            # REST backend on http://localhost:8081 (owns device I/O)
hsnc-web serve --debug  # web UI on http://localhost:8080, in a second shell
```

`HSNC_USE_MOCK_DEVICES=1` (the default) uses demo providers — no hardware needed.
Point the frontend at a non-default backend with `HSNC_API_BASE_URL` (and
`HSNC_API_TOKEN` if set).

## Everyday tasks (Makefile)

```bash
make check        # fast compile-check of all sources
make lint         # ruff
make unit         # pytest (both packages)
make integration  # smoke test against fake SSH containers (needs docker)
make test         # unit + integration
make all          # check + lint + test
make fakes-up     # start fake SSH devices; fakes-down to stop
```

Targets auto-use `.venv`; override with `make PYTHON=/path/to/python <target>`.
Or run tools directly: `(cd hsnc && pytest && ruff check src tests)`.

## Testing model

- **Unit** tests use fakes (fake SSH runner, fake monitoring providers) — fast,
  no network, no `pysnmp` required.
- **Integration** smoke tests run against the throwaway SSH simulators in
  [`fakes/`](../../fakes/). The web suite has a golden-HTML safety net (regenerate
  with `REGEN_GOLDEN=1` only when templates intentionally change).

## House rules

- Keep `make lint && make unit` green for both packages.
- Respect the dependency direction; wire new adapters only in `container.py`.
- Secrets from the environment only. Optional deps (paramiko, pysnmp) stay
  lazily imported so the core runs without them.
