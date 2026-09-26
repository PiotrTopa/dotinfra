---
id: wireguard
kind: network
title: wireguard — wg0 overlay 10.99.0.0/24
status: active
role: Hub-and-spoke VPN joining the LAN, the VPS and roaming devices
tags: [network, vpn]
depends_on: [hub]
updated: 2026-09-20
---

# wireguard — wg0 overlay 10.99.0.0/24

## Overview

Hub and spoke: every peer connects to [hub](../servers/hub.md)
(`vps.example.net:51820`), which forwards between peers and routes the home
LAN through the [nas](../servers/nas.md) site gateway.

## Access

Add a peer: generate keys on the new device, add a `[Peer]` block on the hub
and a row below, then `wg syncconf wg0 <(wg-quick strip wg0)` on the hub.
Private keys stay on each device; the hub's is `wg_hub_private_key` in the vault.

## Configuration

| peer | WireGuard IP | AllowedIPs on the hub |
|---|---|---|
| hub | `10.99.0.1` | — |
| nas (site gateway) | `10.99.0.2` | `10.99.0.2/32, 10.10.0.0/16` |
| laptop | `10.99.0.3` | `10.99.0.3/32` |
| phone | `10.99.0.4` | `10.99.0.4/32` |

- `PersistentKeepalive = 25` on every spoke (NAT traversal).
- MTU 1380 on all peers (the fibre link has a smaller MTU).

## Constraints & known issues

- Everything depends on `hub`: when it is down, remote access and roaming
  metrics are gone (the LAN itself is unaffected).
