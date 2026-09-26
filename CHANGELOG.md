# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] — 2026-09-26

First public release.

### Added

- Markdown CMDB layout (`servers/`, `networks/`, `domains/`, `routers/`,
  `services/`, `devices/`) with a strict YAML-subset frontmatter parser.
- `init`, `new`, `ls`, `show`, `lint` (schema, references, staleness, leaked
  secrets), `index`, `ssh-config` (ProxyJump from `ssh.jump`), `doctor`.
- Vault with `file` and `age` backends: `list`, `get`, `set`, `rm`, `exec`,
  `import` (legacy flat JSON), `migrate`, `rekey`.
- Git sync through a hub and/or peers, section-aware merge driver (frontmatter
  per key, body per H2 section, History union), `reconcile`, `status`, `peer`,
  `timer` (systemd user timer, cron fallback).
- `drift` SSH fact probe with `--update`.
- Agent rules (`AGENTS.md`, `CLAUDE.md`) and Agent Skills: `infra-cmdb`,
  `infra-vault`, `infra-sync`, `infra-onboard`, `infra-monitoring`;
  `skills install`.
- Monitoring: Prometheus file_sd targets from `metrics:`, a docker-compose
  bundle (Prometheus, Grafana, Pushgateway, optional node_exporter and DCGM
  exporter), the Fleet Overview dashboard, `grafana push`, and an event log on
  Grafana annotations (`event add|list|rm`).
- Fictional example CMDB `examples/homelab`.

[Unreleased]: https://github.com/PiotrTopa/dotinfra/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PiotrTopa/dotinfra/releases/tag/v0.1.0
