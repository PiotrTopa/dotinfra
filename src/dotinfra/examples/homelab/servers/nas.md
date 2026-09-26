---
id: nas
kind: server
title: nas — storage, backups and monitoring host
status: active
role: ZFS storage, nightly backups, WireGuard site gateway, runs the monitoring stack
tags: [storage, docker]
address: 10.10.0.10
os: Debian 12
ssh:
  user: alice
  port: 22
  jump: hub
metrics: [node:9100]
secrets: [nas_sudo, nas_backup_passphrase]
depends_on: [lan, ups]
updated: 2026-09-24
---

# nas — storage, backups and monitoring host

## Overview

Small-form-factor PC with four disks in the hallway cupboard. Everything
important lives here: family photos, the model cache for `gpu1`, and the
offsite backup jobs. It is also the WireGuard *site gateway*: the hub routes
`10.10.0.0/16` through it, which is what makes `ssh.jump: hub` work for LAN hosts.

## Configuration

- CPU: 4-core low-power x86; 32 GB ECC RAM.
- ZFS pool `tank`: 2 x mirror of 8 TB disks. Datasets `tank/photos`,
  `tank/models` (NFS export to `gpu1`), `tank/backup`.
- Snapshots: hourly for 48 h, daily for 30 days (`zfs-auto-snapshot`).
- Offsite: `restic` to object storage every night at 03:00, repository key in the vault.
- WireGuard peer `10.99.0.2/32`, `AllowedIPs` on the hub include `10.10.0.0/16`.
- Docker: runs the [monitoring](../services/monitoring.md) bundle.
- NUT client for the [ups](../devices/ups.md): shuts down at 20 % battery.

## Access

`ssh nas`. From outside the LAN the generated SSH config jumps through `hub`.

## Secrets

- `nas_sudo` — sudo password for `alice`.
- `nas_backup_passphrase` — restic repository passphrase.

## Known issues

- Disk 3 (`ata-EXAMPLE-8TB-C`) logged 8 reallocated sectors in August; watch
  `smartctl -A` monthly, a spare disk is on the shelf.

## History

- 2026-09-24 — scrub completed, 0 errors; 61 % pool usage
- 2026-08-17 — disk 3 reallocated sectors 0 → 8; added Known issues entry
- 2026-06-05 — moved the monitoring stack here from `gpu1`
- 2026-04-02 — enabled NFS export `tank/models` for `gpu1`
