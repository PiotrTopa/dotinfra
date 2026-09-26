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

Lights, heating and the washing-machine notifier, on [pi](../servers/pi.md).
Remote access only over [wireguard](../networks/wireguard.md).

## Access

Web UI at the `url` above; admin `alice` (`ha_admin` in the vault).
`ha_long_lived_token`: API token for scripts on `nas`.
Restart: `ssh pi 'docker restart homeassistant'`.

## Configuration

- Home Assistant 2026.9, container `ghcr.io/home-assistant/home-assistant:stable`,
  host network, config in `/srv/homeassistant`.
- Zigbee (ZHA) on the USB coordinator; 23 devices paired.
- Backups: built-in nightly backup plus the Pi's rsync to `nas`.

## Constraints & known issues

- After a Pi reboot, Zigbee devices take about two minutes to report again.
