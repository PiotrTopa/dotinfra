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

14" laptop that goes everywhere, with an always-on WireGuard address
(`10.99.0.3`), so it stays scrapeable at home and away. Carries a full CMDB clone.

## Access

`ssh laptop` from other devices (through `hub`), only while the lid is open.
No vault keys: the disk passphrase is not stored anywhere.

## Configuration

- Fedora 42; 12 cores, 32 GB RAM, integrated GPU (no DCGM).
- WireGuard: NetworkManager connection `wg-homelab`, peer of `hub`.
- `node_exporter` (Fedora package) on `10.99.0.3:9100`.
- `dotinfra timer install --interval 15m` keeps `~/.infra` in sync.

## Constraints & known issues

- Shows as down on the dashboard whenever it sleeps; gaps are expected.
