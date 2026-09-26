---
id: example.net
kind: domain
title: example.net — infrastructure domain
status: active
role: Stable public names for infrastructure (vps.example.net)
tags: [dns]
address: vps.example.net
updated: 2026-09-20
---

# example.net — infrastructure domain

## Overview

A second, boring domain used only for infrastructure names, so that
experiments on it never break family email on [example.com](example.com.md).

## Configuration

| record | type | value |
|---|---|---|
| `vps.example.net` | A | `203.0.113.10` ([hub](../servers/hub.md)) |
| `vps.example.net` | AAAA | `2001:db8:10::10` |

- DNS hosted by the VPS provider; TTL 300 on the hub records.

## Access

Managed in the VPS provider's console (`hub_provider_console` in the vault).

## Secrets

None of its own.

## Known issues

## History

- 2026-09-20 — confirmed records after hub SSH port change (DNS unaffected)
- 2026-03-12 — registered
