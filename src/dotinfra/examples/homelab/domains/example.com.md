---
id: example.com
kind: domain
title: example.com — family domain
status: active
role: Personal email and the home.example.com LAN zone
tags: [dns]
secrets: [dns_api_token]
updated: 2026-08-30
---

# example.com — family domain

## Overview

The family's main domain: email for everyone and names for home services.
The registrar also hosts the public DNS zone.

## Access

Registrar web UI; DNS changes by API with `dns_api_token` (vault; scoped to
DNS edits for this zone, used by the ACME DNS-01 client on `nas`).

## Configuration

| record | type | value |
|---|---|---|
| `example.com` | MX | the mail provider's servers |
| `example.com` | TXT | SPF: `v=spf1 include:mail.example.org -all` |
| `vpn.example.com` | CNAME | `vps.example.net` |
| `home.example.com` | — | not public; served only by the router's resolver |

- Auto-renews each 14 March; DNSSEC enabled at the registrar.

## Constraints & known issues
