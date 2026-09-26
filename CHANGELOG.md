# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] — 2026-09-26

### Fixed

- Merge driver: a section both devices only *appended* to (two new `Known issues`
  bullets) is merged by keeping both additions instead of a conflict; `updated:`
  emptied on one side no longer merges to the string `None`; non-UTF-8 input falls
  back to `git merge-file` instead of a traceback; `git merge-file` output is read
  as UTF-8 regardless of the locale.
- Sync: `INDEX.md` is regenerated after the component files are reconciled;
  conflict stages are read as bytes; `peer add` refuses option-like URLs.
- Security: `address`/`ssh.*` values that would become an ssh option or an
  ssh_config directive (leading `-`, whitespace, control characters, a quoted
  newline) are a lint error, skipped by `ssh-config` and refused by `drift`.
- Drift: point releases are not OS drift (`Ubuntu 24.04` vs `24.04.1`).
- Lint: also detects age identities, PGP private key blocks, `github_pat_`/`gho_`
  style tokens and `sk-proj-` keys.
- CLI: OS errors and broken pipes are reported without tracebacks; `ls`/`show`
  warn about component files that failed to parse instead of hiding them;
  `grafana`/`event` failures use the same `dotinfra: error:` format as every
  other command and their subcommands are required.
- Vault: warns when the file vault is readable by other users.
- Monitoring: `targets` only prunes JSON files it generated itself.

### Added

- `dotinfra vault identity`: create this device's age identity if missing and
  print its public key — the missing step when adding a device to an age vault.

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

[Unreleased]: https://github.com/PiotrTopa/dotinfra/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/PiotrTopa/dotinfra/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/PiotrTopa/dotinfra/releases/tag/v0.1.0
