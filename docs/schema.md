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

Recommended H2 sections, in this order (the templates contain them):

| section | contents |
|---|---|
| `## Overview` | what it is, where it is, who relies on it |
| `## Configuration` | hardware, software, paths, ports, versions |
| `## Access` | how to get in (SSH alias, console, web UI) |
| `## Secrets` | the vault keys and what each unlocks — never values |
| `## Known issues` | open problems, unverified observations, workarounds |
| `## History` | dated log, newest first |

History lines look like:

```markdown
## History

- 2026-09-24 — scrub completed, 0 errors
- 2026-08-17 — disk 3 reallocated sectors 0 → 8
```

Keep headings stable. The sync merge driver treats each H2 section as a unit
(and merges `History`, `Changelog` or `Log` sections line by line), so renaming
or reordering headings creates avoidable conflicts.

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
unknown keys (with `--strict`).
