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

Tower PC under the desk with one 24 GB NVIDIA GPU. Serves local models to
laptops on the LAN and runs occasional fine-tuning jobs. The `fleet` tag puts
it on the Fleet Overview dashboard; `dcgm:9400` adds GPU panels.

The `facts:` block above was written by `dotinfra drift gpu1 --update`.

## Configuration

- CPU 8 cores / 16 threads, 64 GB RAM, 2 TB NVMe for the OS and scratch.
- NVIDIA driver 570 from the Ubuntu graphics PPA; NVIDIA Container Toolkit.
- Ollama as a systemd service on `10.10.0.21:11434` (LAN only).
- Model cache on NFS: `nas:/tank/models` mounted at `/srv/models`.
- Exporters: `prometheus-node-exporter` package (9100) and the DCGM exporter
  container (9400) started with `docker compose --profile gpu up -d dcgm-exporter`.

## Access

`ssh gpu1`. Wake-on-LAN from `nas`: `wakeonlan 02:00:00:00:00:21`.

## Secrets

- `gpu1_sudo` — sudo password for `alice`.

## Known issues

- If `nas` reboots, the NFS mount hangs Ollama until `systemctl restart srv-models.mount`.

## History

- 2026-09-22 — drift probe: kernel 6.8.0-79; facts updated
- 2026-09-10 — driver 560 → 570; DCGM exporter image bumped to match
- 2026-05-30 — added `dcgm:9400` to metrics
- 2026-04-02 — model cache moved to NFS on `nas`
