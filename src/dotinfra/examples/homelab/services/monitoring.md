---
id: monitoring
kind: service
title: monitoring — Prometheus + Grafana
status: active
role: Metrics, fleet dashboard and the infra event log
tags: [observability, docker]
runs_on: nas
url: http://10.10.0.10:3000
prometheus_url: http://10.10.0.10:9090
secrets: [grafana_password]
depends_on: [nas, wireguard]
updated: 2026-09-26
---

# monitoring — Prometheus + Grafana

## Overview

The dotinfra monitoring bundle (Prometheus, Grafana, Pushgateway) on
[nas](../servers/nas.md), the one monitoring host of this CMDB: `.dotinfra.toml`
names this component in `[monitoring] service`, so every device finds Grafana
and Prometheus here (`dotinfra monitoring where`). Scrape targets and the Fleet
Overview dashboard are generated from this CMDB; infra events (outages, maintenance, changes) are
Grafana annotations recorded with `dotinfra event add`.

## Configuration

- Bundle directory: `~/dotinfra-monitoring` on `nas` (from `dotinfra monitoring render`).
- `docker compose --profile node up -d` — the NAS's own node_exporter runs in the bundle.
- Retention 90 days in the `prometheus_data` volume (mounted at `/prometheus`).
- `nas` is the only device with `[monitoring] role = "server"` (in its untracked
  `.dotinfra.local.toml`, set by `dotinfra monitoring setup-server`); its
  `dotinfra timer install` sync refreshes the file_sd targets after every merge.
  Every other device is a client.
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

- 2026-09-26 — dotinfra 0.2: role = server on nas; the old cron `monitoring targets` line replaced by the sync timer
- 2026-09-24 — re-rendered bundle; targets now use file_sd, no restarts on host changes
- 2026-06-05 — moved from `gpu1` to `nas`; history kept by copying the `prometheus_data` volume
- 2026-05-30 — added DCGM exporter on `gpu1`
