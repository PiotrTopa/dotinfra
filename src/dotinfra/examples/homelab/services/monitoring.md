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
[nas](../servers/nas.md), the one monitoring host: `[monitoring] service`
names this component, so every device finds the URLs here
(`dotinfra monitoring where`). Targets and the Fleet Overview dashboard are
generated from this CMDB.

## Access

Grafana at the `url` above: user `admin`, vault key `grafana_password` (also
used by `dotinfra grafana push`). Prometheus at `prometheus_url`.

## Configuration

- Bundle in `~/dotinfra-monitoring` on `nas`; `docker compose --profile node up -d`
  (the NAS's own node_exporter runs in the bundle).
- Retention 90 days in the `prometheus_data` volume (`/prometheus`).
- `nas` has `[monitoring] role = "server"` in its untracked `.dotinfra.local.toml`;
  its sync timer rewrites the file_sd targets after every merge. Every other
  device is a client.
- Ports 9090/9091/3000 published on `10.10.0.10` only (edited compose `ports:`).
- Events: this example keeps the file event log (`[events] backend = "file"`,
  `events/2026.md`) instead of Grafana annotations.

## Constraints & known issues

- `laptop` shows as down whenever it sleeps; that is expected.
