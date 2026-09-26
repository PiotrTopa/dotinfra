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

What this machine is, where it lives physically, and who relies on it.

## Configuration

- Hardware:
- Storage:
- Key packages / services:

## Access

How to get a shell (`ssh {{id}}` once `dotinfra ssh-config` is installed) and any
console/IPMI fallback.

## Secrets

Vault keys only, e.g. `{{id}}_sudo` (sudo password). Fetch with
`dotinfra vault get KEY` or pipe with `dotinfra vault exec KEY -- CMD`.

## Known issues

## History

- {{date}} — created
