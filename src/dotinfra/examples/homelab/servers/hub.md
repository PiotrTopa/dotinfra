---
id: hub
kind: server
title: hub — WireGuard hub VPS
status: active
role: Public WireGuard hub and SSH jump host for the homelab
tags: [vps, jump]
address: 10.99.0.1
os: Debian 12
ssh:
  user: alice
  host: 203.0.113.10
  port: 2222
metrics: [node:9100]
secrets: [hub_sudo, wg_hub_private_key, hub_provider_console]
depends_on: [example.net]
updated: 2026-09-20
---

# hub — WireGuard hub VPS

## Overview

1 vCPU / 1 GB VPS with the only fixed public IP (`203.0.113.10`,
`vps.example.net`): every device connects to it over WireGuard, and it is the
SSH jump host for the LAN when away. `address` is its WireGuard IP (what
Prometheus scrapes); `ssh.host` is the public IP (how you reach it first).

## Access

`ssh hub` after `dotinfra ssh-config`; the provider's web console as a
fallback. Vault: `hub_sudo` (sudo for `alice`), `wg_hub_private_key`
(also in `/etc/wireguard/`, mode 0600), `hub_provider_console`.

## Configuration

- WireGuard `wg0` `10.99.0.1/24`, UDP 51820; peers in
  [networks/wireguard](../networks/wireguard.md).
- `net.ipv4.ip_forward=1`; routes `10.10.0.0/16` to the `nas` peer (site gateway).
- sshd on port 2222, key-only, `AllowUsers alice`.
- nftables: 2222/tcp and 51820/udp from anywhere; 9100/tcp only on `wg0`.
- Debian 12, unattended security upgrades; node_exporter on `10.99.0.1:9100`.

## Constraints & known issues

- The provider reboots hosts for maintenance about twice a year (a week's
  notice by email); WireGuard peers reconnect on their own.
