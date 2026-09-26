---
id: ups
kind: device
title: ups — 1500 VA line-interactive UPS
status: active
role: Battery backup for nas, router and pi
tags: [power]
updated: 2026-08-17
---

# ups — 1500 VA line-interactive UPS

## Overview

Rack-less tower UPS in the hallway cupboard. Powers [nas](../servers/nas.md),
[router](../routers/router.md), the ONT and [pi](../servers/pi.md). Runtime at
normal load is about 25 minutes.

## Configuration

- USB to `nas`, which runs the NUT server (`upsd`); the router and Pi are NUT clients.
- Shutdown order at 20 % battery: pi, gpu1 (not on the UPS, signalled over LAN), nas last.

## Access

No network interface; status with `upsc ups@10.10.0.10` from any LAN host.

## Secrets

None.

## Known issues

- Battery installed 2024-11; plan replacement around 2027-11.

## History

- 2026-08-17 — self-test passed, runtime 26 min at 140 W
- 2026-02-01 — created
