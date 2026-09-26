# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] — 2026-09-26

Upgrading from 0.1.x: `pipx upgrade dotinfra` (or `pip install --user -U
git+https://github.com/PiotrTopa/dotinfra`), then `dotinfra migrate` in the CMDB
and `dotinfra sync`; repeat on every device. See [docs/upgrading.md](docs/upgrading.md).

### Added

- **Self-explanatory CMDB README.** The CMDB's `README.md` now starts with "Start here
  — new machine": install command, `git clone <real URL> ~/.infra`, `dotinfra doctor`,
  skills, vault access for the file and age backends, the sync timer, which machine
  runs monitoring, and the minimum dotinfra version. `init --remote URL` adds the hub
  remote and records the clone URL (`[sync] remote_url`); `migrate` fills it in from
  `git remote get-url` later. Credentials in http(s) URLs are never written.
- **Managed blocks.** README.md, AGENTS.md, CLAUDE.md, .gitignore and .gitattributes keep
  dotinfra's content between `dotinfra:managed` markers; text outside them is yours
  and survives every refresh.
- **`dotinfra migrate [--dry-run] [--yes]`**: numbered schema migrations keyed by
  `[cmdb] schema` (0.1.x = 0 → 1), raises `[cmdb] min_version`, refreshes managed blocks
  (untouched 0.1.x files are replaced, edited ones keep your text below the new block),
  refreshes project and recorded user skills, and commits `migrate: dotinfra X.Y.Z`.
  Idempotent.
- **`dotinfra upgrade [--check] [--pre]`**: detects pipx / pip --user / virtualenv installs,
  runs the matching upgrade and then `migrate --yes` inside a CMDB; refuses source
  checkouts. `--check` compares with the latest GitHub release (offline-safe).
- **Version guard.** A CMDB whose `min_version` is newer than the installed dotinfra
  makes commands exit 3 (`ls`, `show`, `doctor`, `skills status`, `upgrade` warn).
  `sync` checks the `.dotinfra.toml` of incoming commits before merging and refuses
  (exit 3, nothing merged, local commit kept) when they need a newer dotinfra.
- **`.dotinfra.local.toml`**: untracked per-device overrides deep-merged over
  `.dotinfra.toml` (device name, vault paths, monitoring role, URLs over a VPN).
- **Monitoring lives on one machine.** `[monitoring] service` names the monitoring service
  component; Grafana/Prometheus URLs are derived from it (`url`, new `prometheus_url`
  frontmatter key, its address or its `runs_on` server's), with explicit URLs as
  overrides. New `dotinfra monitoring where [--check]` and `monitoring setup-server`;
  on the monitoring host (`role = "server"`) every successful sync refreshes the
  Prometheus targets; on clients `render`/`targets` warn unless `--output`/`--force`.
- **Agent Skills for more agents**: `skills install --target` takes a list of `claude`,
  `agents`, `copilot`, `cline`, `antigravity` (`agy`), `codex`, `gemini`, or `all` /
  `auto` (default: detected agents); `--scope user|project|both`; `skills status`.
  Paths follow each agent's documentation (listed in docs/agents.md); agents that
  read the shared `.agents/skills` directories are installed there once. `init`
  installs both scopes for the detected agents (asks on a terminal; `--skills`,
  `--skills-scope`, `--yes`), committing project-scope skills into the CMDB so every
  clone has them. Installs are recorded so `migrate` can refresh them.
- `doctor`: rows for the dotinfra version vs `min_version`, pending migrations, skills
  per agent and scope (current/stale/missing), the monitoring role and host, and
  available updates with `--check-updates`.

### Changed

- The config template no longer writes `device` or the localhost monitoring URLs into
  the shared `.dotinfra.toml`; migrating from 0.1 comments out URLs that equal the old
  localhost defaults so the service component takes over (other URLs are kept).
- `init --skills` defaults to `auto` instead of `none`.
- `skills install` rewrites only skills whose content changed.
- The `infra-monitoring` skill's `.env` example line no longer trips the CMDB's own
  secret scan when the skills are committed into a CMDB.

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

[Unreleased]: https://github.com/PiotrTopa/dotinfra/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/PiotrTopa/dotinfra/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/PiotrTopa/dotinfra/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/PiotrTopa/dotinfra/releases/tag/v0.1.0
