---
id: laptop
kind: server
title: laptop — Alice's laptop
status: active
role: Daily driver; carries a full CMDB clone and syncs it
tags: [fleet, mobile]
address: 10.99.0.3
os: Fedora 42
ssh:
  user: alice
  port: 22
  jump: hub
metrics: [node:9100]
secrets: []
depends_on: [wireguard]
updated: 2026-09-18
---

# laptop — Alice's laptop

## Overview

14" laptop that goes everywhere. WireGuard is always on, so it keeps the same
address (`10.99.0.3`) at home and away and stays scrapeable. It shows up on
the dashboard only while it is awake; gaps in its graphs are expected.

## Configuration

- 12 cores, 32 GB RAM, integrated GPU (no DCGM).
- WireGuard via NetworkManager connection `wg-homelab`, peer of `hub`.
- `node_exporter` from the Fedora package, bound to `10.99.0.3:9100`.
- `dotinfra timer install --interval 15m` keeps `~/.infra` in sync.

## Access

`ssh laptop` from other devices (through `hub`). Only reachable while the
lid is open.

## Secrets

None stored for this host; the disk passphrase is in Alice's head.

## Known issues

## History

- 2026-09-18 — reinstalled with Fedora 42; restored `~/.infra` with `git clone` from the hub
- 2026-05-11 — created
