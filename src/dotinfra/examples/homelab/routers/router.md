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
with a dynamic public IP (currently `198.51.100.24`).

## Access

Web UI at the `url` above (`router_admin` in the vault); SSH for `alice`,
key auth only.

## Configuration

- LAN `10.10.0.1/16` on `igc1`; DHCP pool `10.10.100.1`–`10.10.199.254`,
  static leases for every host in this CMDB.
- No port forwards: remote access goes through `hub`.
- Unbound resolver, DNS-over-TLS upstream; local zone `home.example.com`.
- Plugin `os-node_exporter` on the LAN interface only.
- Config backup nightly to `nas` (built-in SFTP backup).

## Constraints & known issues

- Dynamic WAN IP: never point DNS at it; public names go to `hub`.
