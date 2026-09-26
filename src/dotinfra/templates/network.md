---
id: {{id}}
kind: network
title: {{title}}
status: planned            # active | planned | degraded | retired
role:                      # one line: what this network carries
tags: []
address: {{address}}       # CIDR or gateway, e.g. 10.10.0.0/24
depends_on: []             # e.g. the router that serves it
updated: {{date}}
---

# {{title}}

## Overview

Purpose, physical/virtual medium (LAN, VLAN, WireGuard, Tailscale...).

## Configuration

- Subnet:
- Gateway:
- DHCP range / static leases:
- DNS:

## Access

Who and what can reach this network, and from where.

## Secrets

Vault keys only (Wi-Fi PSKs, VPN private keys...).

## Known issues

## History

- {{date}} — created
