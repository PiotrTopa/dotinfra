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

A 1 vCPU / 1 GB VPS at a small hosting provider. It has the only public IP
that never changes (`203.0.113.10`, DNS `vps.example.net`), so every other
device connects to it over WireGuard and it is the SSH jump host for the LAN
when you are away from home.

`address` is its WireGuard IP (`10.99.0.1`) because that is where Prometheus
scrapes it; `ssh.host` is the public IP because that is how you reach it first.

## Configuration

- WireGuard interface `wg0`, `10.99.0.1/24`, listening on UDP 51820.
  Peers and AllowedIPs are listed in [networks/wireguard](../networks/wireguard.md).
- `net.ipv4.ip_forward=1`; routes `10.10.0.0/16` to the `nas` peer (site gateway).
- sshd on port 2222, key-only, `AllowUsers alice`.
- nftables: allow 2222/tcp and 51820/udp from anywhere; 9100/tcp only on `wg0`.
- node_exporter from Debian packages, listening on `10.99.0.1:9100`.
- Unattended upgrades enabled (security only).

## Access

`ssh hub` after `dotinfra ssh-config`. Provider web console as a fallback
(login in the vault under `hub_provider_console`, not needed day to day).

## Secrets

- `hub_sudo` — sudo password for `alice`.
- `wg_hub_private_key` — WireGuard private key (also on disk in `/etc/wireguard/`, mode 0600).
- `hub_provider_console` — login for the hosting provider's web console.

## Known issues

- The provider reboots hosts for maintenance about twice a year with a
  week's notice by email; WireGuard peers reconnect on their own.

## History

- 2026-09-20 — moved sshd to port 2222; updated `ssh.port`
- 2026-07-02 — upgraded to Debian 12.11, kernel 6.1
- 2026-03-14 — created; replaces port-forwarding on the home router
