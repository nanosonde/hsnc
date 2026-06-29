# ADR 0003 — Server-rendered frontend (Jinja2 + HTMX, no Node build)

**Status:** Accepted

## Context

This is a self-hosted controller for small networks, maintained by a small team.
A SPA toolchain (Node, bundlers, npm dependency churn) adds heavy build and
supply-chain overhead for a UI that is mostly forms and tables.

## Decision

Render HTML on the server with Jinja2. Use **HTMX** for the few dynamic bits
(client search, pagination) by swapping server-rendered partials. Ship one
hand-written CSS file with CSS variables and a tiny `ui.js`. **No Node/JS build
pipeline** — the browser loads exactly what is in the repo.

## Consequences

- No build step, no `node_modules`, smaller supply-chain surface.
- Page logic lives in Python blueprints; partials returned on `HX-Request`.
- Rich client-side interactivity would require revisiting this choice.
- Styling is centralized in `:root` CSS variables — change once, restyle all.
