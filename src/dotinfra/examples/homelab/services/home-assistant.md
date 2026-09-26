---
id: home-assistant
kind: service
title: home-assistant — home automation
status: active
role: Home Assistant with Zigbee devices
tags: [iot, docker]
runs_on: pi
address: 10.10.0.40
url: http://10.10.0.40:8123
secrets: [ha_admin, ha_long_lived_token]
depends_on: [pi, lan]
updated: 2026-09-12
---

# home-assistant — home automation

## Overview

Lights, heating and the washing-machine notifier. Runs on [pi](../servers/pi.md).
Reachable remotely only over [wireguard](../networks/wireguard.md).

## Configuration

- Container `ghcr.io/home-assistant/home-assistant:stable`, host network,
  config in `/srv/homeassistant`.
- Zigbee (ZHA) on the USB coordinator; 23 devices paired.
- Backups: built-in nightly backup plus the Pi's rsync to `nas`.

## Access

Web UI at the `url` above. Admin user `alice` (`ha_admin` in the vault).
Restart: `ssh pi 'docker restart homeassistant'`.

## Secrets

- `ha_admin` — admin login.
- `ha_long_lived_token` — API token used by scripts on `nas`.

## Known issues

- After a Pi reboot, Zigbee devices take about two minutes to report again.

## History

- 2026-09-12 — updated to 2026.9; re-paired the hallway sensor
- 2026-04-20 — migrated with the Pi to the SSD
