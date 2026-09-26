---
id: gpu1
kind: server
title: gpu1 — GPU workstation
status: active
role: Local LLM inference and batch GPU jobs (Ollama)
tags: [fleet, gpu, docker]
address: 10.10.0.21
os: Ubuntu 24.04 LTS
ssh:
  user: alice
  port: 22
  jump: hub
metrics: [node:9100, dcgm:9400]
secrets: [gpu1_sudo]
depends_on: [nas, lan]
facts:
  hostname: gpu1
  kernel: Linux 6.8.0-79-generic
  arch: x86_64
  cpus: 16
  mem_gb: 64
  ips: [10.10.0.21]
  probed: 2026-09-22
updated: 2026-09-22
---

# gpu1 — GPU workstation

## Overview

Tower PC under the desk with one 24 GB NVIDIA GPU: serves local models to the
LAN (Ollama) and runs occasional fine-tuning jobs. `facts:` above come from
`dotinfra drift gpu1 --update`.

## Access

`ssh gpu1` (through `hub` when away). Wake-on-LAN from `nas`:
`wakeonlan 02:00:00:00:00:21`. Vault: `gpu1_sudo` (sudo for `alice`).

## Configuration

- 8 cores / 16 threads, 64 GB RAM, 2 TB NVMe (OS and scratch).
- NVIDIA driver 570 (Ubuntu graphics PPA), NVIDIA Container Toolkit.
- Ollama as a systemd service on `10.10.0.21:11434`, LAN only.
- Model cache on NFS: `nas:/tank/models` at `/srv/models`.
- Exporters: `prometheus-node-exporter` (9100); DCGM exporter container (9400),
  `docker compose --profile gpu up -d dcgm-exporter`.

## Constraints & known issues

- If `nas` reboots, the NFS mount hangs Ollama until
  `systemctl restart srv-models.mount`.
- Not on the UPS; `nas` signals it to shut down over the LAN.
