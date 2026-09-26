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

Small-form-factor PC with four disks in the hallway cupboard: family photos,
the model cache for `gpu1`, offsite backups and the monitoring stack. Also the
WireGuard *site gateway*: the hub routes `10.10.0.0/16` through it, which is
what makes `ssh.jump: hub` work for LAN hosts.

## Access

`ssh nas` (through `hub` from outside the LAN). Vault: `nas_sudo` (sudo for
`alice`), `nas_backup_passphrase` (restic repository).

## Configuration

- 4-core low-power x86, 32 GB ECC RAM.
- ZFS pool `tank`: 2 × mirror of 8 TB disks, 61 % used. Datasets
  `tank/photos`, `tank/models` (NFS export to `gpu1`), `tank/backup`.
- Snapshots hourly for 48 h, daily for 30 days (`zfs-auto-snapshot`); monthly scrub.
- Offsite: `restic` to object storage nightly at 03:00.
- WireGuard peer `10.99.0.2/32`.
- Docker: the [monitoring](../services/monitoring.md) bundle.
- NUT server for the [ups](../devices/ups.md); shuts down at 20 % battery.

## Constraints & known issues

- Disk 3 (`ata-EXAMPLE-8TB-C`) has 8 reallocated sectors: check
  `smartctl -A` monthly; a spare disk is on the shelf.
