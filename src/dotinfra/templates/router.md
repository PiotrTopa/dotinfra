---
id: {{id}}
kind: router
title: {{title}}
status: planned            # active | planned | degraded | retired
role:                      # one line, e.g. "home gateway, DHCP, WireGuard hub"
tags: []
address: {{address}}       # management IP
os:                        # firmware, e.g. OpenWrt 24.10
ssh:
  user: root
  port: 22
metrics: []                # e.g. [node:9100]
secrets: []                # vault keys, e.g. [{{id}}_admin]
depends_on: []
updated: {{date}}
---

# {{title}}

## Overview

Model, location, uplink (ISP, modem), networks it serves (2–3 lines).

## Access

Web UI URL, SSH, recovery procedure if it bricks. Vault keys: `{{id}}_admin`.

## Configuration

- WAN:
- LAN / VLANs:
- Port forwards:
- Firewall rules worth knowing:
- VPN:

## Constraints & known issues
