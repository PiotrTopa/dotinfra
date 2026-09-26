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

Purpose and medium (LAN, VLAN, WireGuard, Tailscale...), 2–3 lines.

## Access

Who and what can reach this network, and from where. Vault keys (Wi-Fi PSK,
VPN keys) by name only.

## Configuration

- Subnet:
- Gateway:
- DHCP range / static leases:
- DNS:

## Constraints & known issues
