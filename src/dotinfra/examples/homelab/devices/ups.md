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

Tower UPS in the hallway cupboard powering [nas](../servers/nas.md),
[router](../routers/router.md), the ONT and [pi](../servers/pi.md).
Runtime at normal load (≈ 140 W) is about 25 minutes.

## Access

No network interface; `upsc ups@10.10.0.10` from any LAN host.

## Configuration

- USB to `nas`, which runs the NUT server (`upsd`); router and Pi are NUT clients.
- Shutdown order at 20 % battery: pi, gpu1 (not on the UPS, signalled over
  the LAN), nas last.

## Constraints & known issues

- Battery from 2024-11; replace around 2027-11.
