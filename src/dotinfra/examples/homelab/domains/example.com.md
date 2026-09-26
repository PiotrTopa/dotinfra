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
Registered at a registrar that also hosts the public DNS zone.

## Configuration

| record | type | value |
|---|---|---|
| `example.com` | MX | the mail provider's servers |
| `example.com` | TXT | SPF: `v=spf1 include:mail.example.org -all` |
| `vpn.example.com` | CNAME | `vps.example.net` |
| `home.example.com` | — | not public; served only by the router's resolver |

- Renewal: auto-renew each 14 March; card on file.
- DNSSEC enabled at the registrar.

## Access

Registrar web UI; DNS changes by API with the token below
(used by the ACME DNS-01 client on `nas`).

## Secrets

- `dns_api_token` — registrar API token, scoped to DNS edits for this zone.

## Known issues

## History

- 2026-08-30 — rotated `dns_api_token`; the old one is revoked
- 2026-03-14 — added `vpn.example.com`
