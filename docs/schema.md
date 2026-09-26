# Component schema

Every `*.md` file in `servers/`, `networks/`, `domains/`, `routers/`,
`services/` or `devices/` is a component. It starts with a frontmatter block
between `---` lines, followed by Markdown.

Files ending in `.local.md` are ignored (and not synced). Files at the CMDB
root (`README.md`, `AGENTS.md`, `CLAUDE.md`, `INDEX.md`) are not components.

## Frontmatter syntax

dotinfra parses frontmatter with its own small parser — a strict **subset of
YAML**, so files stay readable by any YAML tool but nothing surprising sneaks in.

```yaml
---
# comments on their own line are fine
id: gpu1                         # trailing comments after unquoted values too
title: "gpu1 — GPU workstation"  # quotes are optional and stripped
status: active
tags: [fleet, gpu, "two words"]  # inline list
depends_on:                      # block list (scalars only)
  - nas
  - lan
ssh:                             # one-level map
  user: alice
  port: 22
  jump: hub
facts:
  ips: [10.10.0.21]              # inline list inside a map is allowed
enabled: true                    # true/false -> boolean
cpus: 16                         # integers -> int
note:                            # empty, null or ~ -> no value
updated: 2026-09-26              # dates stay strings
---
```

Not supported (a parse error with file and line): multi-line strings (`|`,
`>`), anchors and aliases, maps nested deeper than one level, lists of maps,
flow maps (`{a: 1}`).

## Fields

| field | type | required | meaning |
|---|---|---|---|
| `id` | string matching `[a-z0-9][a-z0-9._-]*` | no — defaults to the file name, lowercased | unique across the CMDB |
| `kind` | `server` `network` `domain` `router` `service` `device` | no — derived from the folder | must match the folder if given |
| `title` | string | no — defaults to the first `# H1`, else the id | display name |
| `status` | `active` `planned` `degraded` `retired` | **yes** | lifecycle state |
| `role` | string | recommended | one line: what it is for |
| `tags` | list | no | free labels; `fleet` puts a host on the fleet dashboard |
| `address` | string | no | primary IP or hostname; also where metrics are scraped |
| `os` | string | no | e.g. `Debian 12` |
| `ssh` | map: `user`, `host`, `port`, `jump`, `key` | no | `host` defaults to `address`; `jump` is another component's **id** |
| `metrics` | list of `job:port` | no | Prometheus targets at `address`, e.g. `[node:9100, dcgm:9400]` |
| `labels` | map | no | extra Prometheus target labels; `host` overrides the id in `host`/`instance` (keep existing series names, e.g. `host: GPU1`); `job`/`instance` are reserved |
| `secrets` | list | no | vault **key names** this component needs |
| `depends_on` | list of ids | no | components this one needs |
| `runs_on` | id | no (services) | the server hosting a service |
| `url` | string | no | web UI or endpoint (monitoring service: the Grafana URL) |
| `prometheus_url` | string | no | monitoring service only: the Prometheus URL (default `http://<address>:9090`) |
| `facts` | map | no | written by `dotinfra drift --update`: hostname, kernel, arch, cpus, mem_gb, ips, probed |
| `updated` | `YYYY-MM-DD` | recommended | last time the file was reconciled with reality |

Unknown keys are allowed; `dotinfra lint --strict` warns about them. Use them
freely for your own conventions (`location:`, `warranty:`, `vlan:`).

### Choosing `address`

`address` is what the monitoring host and the SSH client use by default. For a
roaming laptop or a remote VPS, the VPN address is usually the right choice
(constant and reachable from the monitoring host). When you first reach a host
by a different address (e.g. a VPS's public IP), set `ssh.host` to that.

## Body

**Documents state what is; events go to the event log.** A component body is
a concise fact sheet of the current state. Agents read these files on every
infra task, so every line costs context: a doc should be cheap to read and
hold only what someone would act on today.

Recommended H2 sections, in this order (the templates contain them):

| section | contents |
|---|---|
| `## Overview` | 2–3 lines: what it is, where it is, who relies on it |
| `## Access` | how to get in (SSH alias, console, web UI); vault key names and what each unlocks — never values |
| `## Configuration` (or `## Hardware`, `## Services`) | hardware, software, paths, ports, versions |
| `## Constraints & known issues` | limits, open problems, unverified observations, workarounds |

Maintaining it:

- On every change, **edit the facts in place**: rewrite the line that is no
  longer true. Never append a journal ("2026-09-24 — did X").
- **Remove resolved issues.** The doc says what is wrong *now*.
- **Events and history go to `dotinfra event add`** ([events](events.md)).
  Git history keeps every earlier version of the doc.
- **Length**: aim for ≈ 40 lines or fewer for a simple component, 80 for a
  complex one. `dotinfra lint` warns above `[lint] max_lines` (default 120).

Keep headings stable. The sync merge driver treats each H2 section as a unit,
so renaming or reordering headings creates avoidable conflicts. (Docs written
before 0.3 may still have a `History`/`Changelog`/`Log` section; the driver
still unions those line by line, and lint flags them as `journal`.)

## Lint rules

`dotinfra lint` exits 1 on errors:

- frontmatter parse error; missing or invalid `status`; bad `id`; duplicate `id`;
  `kind` not matching its folder;
- `ssh.jump`, `depends_on` or `runs_on` pointing at an unknown id;
- a malformed `metrics` entry;
- an `address` or `ssh.*` value starting with `-` or containing whitespace or
  control characters (it would become an ssh option or an ssh_config directive);
- secret-looking content anywhere in a tracked file: private key blocks, age
  identities, `password: <value>`, AWS access keys, GitHub tokens, `sk-...` API
  keys, Slack tokens. A line containing `dotinfra:allow-secret` is exempt.

Warnings: missing `role`; missing `updated` or older than 180 days; no H1;
a key in `secrets` that the vault does not have (when the vault is readable);
unknown keys (with `--strict`); `journal` — an H2 like `History`, `Changelog`,
`Log`, `Event history` or `Historical ...`, or more than 5 lines starting with a
date (move history to `dotinfra event add`, keep current facts); `long` — a
body longer than `[lint] max_lines` (default 120).

Files under `events/` are not components: they are not loaded, indexed or
checked by the component rules (the secret scan still covers them).
