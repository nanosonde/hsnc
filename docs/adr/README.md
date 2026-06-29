# Architecture Decision Records

Each ADR captures one significant decision: its context, the decision, and its
consequences. Records are immutable — when a decision changes, a new ADR
supersedes the old one. Derived from the project's commit history.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-clean-architecture.md) | Clean Architecture with ports & adapters | Accepted |
| [0002](0002-two-package-split.md) | Two standalone packages (backend + frontend) | Accepted |
| [0003](0003-server-rendered-frontend.md) | Server-rendered Jinja2 + HTMX, no Node build | Accepted |
| [0004](0004-polyglot-storage.md) | YAML config · SQLite telemetry · JSONL history | Accepted |
| [0005](0005-backend-owns-device-io.md) | Backend owns all device I/O over a REST API | Accepted (supersedes broker) |
| [0006](0006-config-vs-monitoring-planes.md) | Split config plane (SSH) from monitoring plane | Accepted |
| [0007](0007-declarative-staged-apply.md) | Declarative config with staged review/apply/revert | Accepted |
| [0008](0008-read-only-by-default.md) | Read-only mode on by default | Accepted |
| [0009](0009-secrets-from-environment.md) | Secrets only from the environment | Accepted |
| [0010](0010-pluggable-secondary-monitoring.md) | Pluggable secondary monitoring, strict selection | Accepted |
| [0011](0011-per-platform-device-packages.md) | Per-platform device packages | Accepted |
| [0012](0012-docker-s6-two-processes.md) | Docker + s6-overlay, two supervised processes | Accepted |
| [0013](0013-mock-and-fakes.md) | Mock providers + fake SSH containers for dev/test | Accepted |
| [0014](0014-agpl-license.md) | AGPL-3.0-or-later license | Accepted |

## Format

Each record: **Context → Decision → Consequences**, plus status. Keep them short.
