---
id: {{id}}
kind: domain
title: {{title}}
status: planned            # active | planned | degraded | retired
role:                      # one line: what this domain is used for
tags: []
address: {{address}}       # the domain name itself, e.g. example.com
url:                       # main site, if any
secrets: []                # vault keys, e.g. registrar or DNS API tokens
depends_on: []
updated: {{date}}
---

# {{title}}

## Overview

Registrar, renewal date, who owns the account.

## Configuration

- Nameservers:
- Important records (A/AAAA/CNAME/MX/TXT):
- TLS certificates (issuer, renewal mechanism):

## Access

Where the DNS is managed and how to log in (vault key names, not passwords).

## Secrets

Vault keys only.

## Known issues

## History

- {{date}} — created
