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

Every peer connects to [hub](../servers/hub.md) (`vps.example.net:51820`).
The hub forwards between peers and routes the home LAN through the
[nas](../servers/nas.md), which acts as the site gateway.

## Configuration

| peer | WireGuard IP | AllowedIPs on the hub |
|---|---|---|
| hub | `10.99.0.1` | — |
| nas (site gateway) | `10.99.0.2` | `10.99.0.2/32, 10.10.0.0/16` |
| laptop | `10.99.0.3` | `10.99.0.3/32` |
| phone | `10.99.0.4` | `10.99.0.4/32` |

- `PersistentKeepalive = 25` on every spoke (NAT traversal).
- MTU 1380 on all peers (the fibre link has a smaller MTU).

## Access

Add a peer: generate keys on the new device, add a `[Peer]` block on the hub,
add a row to the table above, `wg syncconf wg0 <(wg-quick strip wg0)` on the hub.

## Secrets

Private keys stay on each device. The hub's key is in the vault as
`wg_hub_private_key` (see [hub](../servers/hub.md)).

## Known issues

## History

- 2026-09-20 — hub SSH moved to 2222; WireGuard unchanged
- 2026-05-11 — added laptop peer 10.99.0.3
- 2026-03-14 — created
