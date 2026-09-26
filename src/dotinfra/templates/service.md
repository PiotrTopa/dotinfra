---
id: {{id}}
kind: service
title: {{title}}
status: planned            # active | planned | degraded | retired
role:                      # one line: what the service does
tags: []
runs_on:                   # id of the server hosting it
address: {{address}}       # host:port or hostname it listens on
url:                       # web UI / API endpoint
metrics: []                # e.g. [app:8080]
secrets: []                # vault keys, e.g. [{{id}}_admin_token]
depends_on: []
updated: {{date}}
---

# {{title}}

## Overview

What it does and who uses it (2–3 lines).

## Access

URLs, admin accounts (vault key names), how to restart it.

## Configuration

- Install method (package, container, compose file path):
- Config files:
- Data directory and backups:
- Ports:

## Constraints & known issues
