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

Raspberry Pi 4 (4 GB) with an SSD over USB 3, mounted next to the router.
Hosts [home-assistant](../services/home-assistant.md) and a USB Zigbee stick.

## Configuration

- Boots from USB SSD; SD card removed.
- Docker with Home Assistant in host network mode (`/srv/homeassistant`).
- Zigbee coordinator on `/dev/ttyUSB0`, passed through to the container.
- Nightly `rsync` of `/srv/homeassistant` to `nas:/tank/backup/pi/` (one-way
  backup of data, not of the CMDB).
- `prometheus-node-exporter` package on port 9100.

## Access

`ssh pi`.

## Secrets

- `pi_sudo` — sudo password for `alice`.

## Known issues

- CPU throttles above 80 °C in summer; a fan case is on order.

## History

- 2026-09-12 — added `metrics: [node:9100]` after installing node_exporter
- 2026-07-21 — throttling seen during a heat wave; noted in Known issues
- 2026-04-20 — moved from SD card to USB SSD
