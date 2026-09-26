---
id: monitoring
kind: service
title: monitoring — Prometheus + Grafana
status: active
role: Metrics, fleet dashboard and the infra event log
tags: [observability, docker]
runs_on: nas
address: 10.10.0.10
url: http://10.10.0.10:3000
secrets: [grafana_password]
depends_on: [nas, wireguard]
updated: 2026-09-24
---

# monitoring — Prometheus + Grafana

## Overview

The dotinfra monitoring bundle (Prometheus, Grafana, Pushgateway) on
[nas](../servers/nas.md). Scrape targets and the Fleet Overview dashboard are
generated from this CMDB; infra events (outages, maintenance, changes) are
Grafana annotations recorded with `dotinfra event add`.

## Configuration

- Bundle directory: `~/dotinfra-monitoring` on `nas` (from `dotinfra monitoring render`).
- `docker compose --profile node up -d` — the NAS's own node_exporter runs in the bundle.
- Retention 90 days in the `prometheus_data` volume (mounted at `/prometheus`).
- Cron on `nas`, every 10 minutes: `dotinfra sync --no-push; dotinfra monitoring targets`.
- Ports 9090/9091/3000 are published on `10.10.0.10` only (edited compose `ports:`).

## Access

Grafana at the `url` above, user `admin`, password in the vault
(`grafana_password`). Prometheus UI at `http://10.10.0.10:9090`.

## Secrets

- `grafana_password` — Grafana admin; also used by `dotinfra grafana push`
  and `dotinfra event`.

## Known issues

- The laptop shows as down whenever it sleeps; that is expected.

## History

- 2026-09-24 — re-rendered bundle; targets now use file_sd, no restarts on host changes
- 2026-06-05 — moved from `gpu1` to `nas`; history kept by copying the `prometheus_data` volume
- 2026-05-30 — added DCGM exporter on `gpu1`
