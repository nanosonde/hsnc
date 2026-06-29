# Getting started

This walks an administrator from nothing to a running controller. The supported
deployment is the bundled Docker image.

## Option A — Hardware-free demo

Try the whole UI (VLAN/port/Wi-Fi editing and the review/apply workflow) with no
real devices. Mock devices are seeded automatically.

```bash
docker build -t hsnc:latest .
docker run --rm -p 8080:8080 -e HSNC_USE_MOCK_DEVICES=1 hsnc:latest
# open http://localhost:8080
```

## Option B — Real devices

The bundled `docker-compose.yml` targets real hardware and refuses to start
without your inventory.

```bash
cp config/devices.yaml.example config/devices.yaml   # then edit for your network
cp .env.example .env                                 # then set passwords/secrets
docker compose up --build                            # or: make up
# open http://<host>:8080
```

- `config/devices.yaml` describes **only how to reach each device** — never
  passwords. See [Managing devices](managing-devices.md).
- Secrets (SSH passwords, SNMP/Prometheus credentials) come from `.env`. See the
  [environment-variable reference](../../README.md#environment-variables).
- To make a device pollable, follow [device setup](../devices/README.md).

## First login

1. Open `http://<host>:8080` and sign in with `admin` / `admin`.
2. **Change both default passwords immediately** (`config/users.yaml`).
3. The controller starts in **read-only mode** — editing config is allowed, but
   applying to devices is blocked. Turn it off with the top-bar toggle when ready
   to push changes. See the [apply workflow](apply-workflow.md).

## Where data lives

Everything persists in the `controller-data` Docker volume:

| File | Holds |
| --- | --- |
| `config/*.yaml` | site, users, device inventory |
| `desired_config.json` | your staged edits |
| `current_config.json` | last config read from devices (the baseline) |
| `runtime.db` | polled status & clients (SQLite, pruned by retention) |
| `history.jsonl` | append-only apply history |

Take a [backup](backups.md) before major changes.
