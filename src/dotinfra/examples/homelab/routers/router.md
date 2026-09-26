---
id: router
kind: router
title: router — OPNsense gateway
status: active
role: Internet gateway, firewall, DHCP and DNS resolver for the LAN
tags: [network]
address: 10.10.0.1
os: OPNsense 25.7
ssh:
  user: alice
  port: 22
  jump: hub
url: https://10.10.0.1
metrics: [node:9100]
secrets: [router_admin]
depends_on: [ups]
updated: 2026-09-05
---

# router — OPNsense gateway

## Overview

Fanless mini PC with four 2.5 GbE ports running OPNsense. WAN is a fibre ONT
with a dynamic public IP (currently `198.51.100.24`); nothing is port-forwarded
since the WireGuard hub took over remote access.

## Configuration

- LAN `10.10.0.1/16` on `igc1`; DHCP pool `10.10.100.1`–`10.10.199.254`,
  static leases for every host in this CMDB.
- Unbound resolver with DNS-over-TLS upstream; local zone `home.example.com`.
- Plugin `os-node_exporter` listening on the LAN interface only.
- Config backup: nightly to `nas` via the built-in SFTP backup.

## Access

Web UI at the `url` above (login `router_admin` in the vault); SSH for
`alice` with key auth only.

## Secrets

- `router_admin` — web UI admin login.

## Known issues

## History

- 2026-09-05 — updated to 25.7; no config changes
- 2026-03-14 — removed the port forward for SSH (replaced by `hub`)
