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

Model, location, uplink (ISP, modem), which networks it serves.

## Configuration

- WAN:
- LAN / VLANs:
- Port forwards:
- Firewall rules worth knowing:
- VPN:

## Access

Web UI URL, SSH, and the recovery procedure if it bricks.

## Secrets

Vault keys only.

## Known issues

## History

- {{date}} — created
