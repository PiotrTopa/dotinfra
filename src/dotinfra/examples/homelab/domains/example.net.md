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

A second, boring domain for infrastructure names only, so experiments never
break family email on [example.com](example.com.md).

## Access

Managed in the VPS provider's console (`hub_provider_console` in the vault).

## Configuration

| record | type | value |
|---|---|---|
| `vps.example.net` | A | `203.0.113.10` ([hub](../servers/hub.md)) |
| `vps.example.net` | AAAA | `2001:db8:10::10` |

- DNS hosted by the VPS provider; TTL 300 on the hub records.

## Constraints & known issues
