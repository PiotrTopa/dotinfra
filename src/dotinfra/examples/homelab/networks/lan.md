---
id: lan
kind: network
title: lan — home LAN 10.10.0.0/16
status: active
role: Flat home LAN behind the router
tags: [network]
depends_on: [router]
updated: 2026-09-05
---

# lan — home LAN 10.10.0.0/16

## Overview

One flat network for everything at home. Infrastructure has static leases in
`10.10.0.0/24`; DHCP clients get `10.10.100.1`–`10.10.199.254`.

## Access

From outside only through [wireguard](wireguard.md), via the `nas` site gateway.

## Configuration

| address | use |
|---|---|
| `10.10.0.1` | [router](../routers/router.md) |
| `10.10.0.10` | [nas](../servers/nas.md) |
| `10.10.0.21` | [gpu1](../servers/gpu1.md) |
| `10.10.0.40` | [pi](../servers/pi.md) |
| `10.10.100.1`–`10.10.199.254` | DHCP pool (phones, TVs, guests) |

- DNS: the router (`10.10.0.1`), search domain `home.example.com`.

## Constraints & known issues

- IoT devices share the LAN; a separate VLAN is planned.
