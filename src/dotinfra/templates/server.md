---
id: {{id}}
kind: server
title: {{title}}
status: planned            # active | planned | degraded | retired
role:                      # one line: what this box is for
tags: [fleet]              # "fleet" = compute boxes shown on the dashboard
address: {{address}}       # primary IP or hostname
os:                        # e.g. Debian 12
ssh:
  user:
  port: 22
  # jump: bastion          # id of the jump host component, if any
  # key: ~/.ssh/id_ed25519
metrics: []                # Prometheus targets at `address`, e.g. [node:9100]
secrets: []                # vault keys (never values), e.g. [{{id}}_sudo]
depends_on: []             # ids of components this one needs
updated: {{date}}
---

# {{title}}

## Overview

What this machine is for, where it lives, who relies on it (2–3 lines).

## Access

`ssh {{id}}` (after `dotinfra ssh-config`); console/IPMI fallback. Vault keys:
`{{id}}_sudo` (sudo password).

## Configuration

- Hardware:
- Storage:
- Services:

## Constraints & known issues
