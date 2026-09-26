---
id: pi
kind: server
title: pi — Raspberry Pi 4 (home automation)
status: active
role: Runs Home Assistant and the Zigbee coordinator
tags: [iot, arm]
address: 10.10.0.40
os: Raspberry Pi OS 12 (bookworm)
ssh:
  user: alice
  port: 22
  jump: hub
metrics: [node:9100]
secrets: [pi_sudo]
depends_on: [lan, nas]
updated: 2026-09-12
---

# pi — Raspberry Pi 4 (home automation)

## Overview

Raspberry Pi 4 (4 GB) booting from a USB 3 SSD, next to the router. Hosts
[home-assistant](../services/home-assistant.md) and a USB Zigbee stick.

## Access

`ssh pi`. Vault: `pi_sudo` (sudo for `alice`).

## Configuration

- Docker; Home Assistant in host network mode (`/srv/homeassistant`).
- Zigbee coordinator on `/dev/ttyUSB0`, passed through to the container.
- Nightly `rsync` of `/srv/homeassistant` to `nas:/tank/backup/pi/`.
- `prometheus-node-exporter` on port 9100.

## Constraints & known issues

- CPU throttles above 80 °C in summer; a fan case is on order.
