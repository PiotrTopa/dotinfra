---
name: infra-cmdb
description: Read and update the user's infrastructure CMDB (a dotinfra folder of Markdown files, usually ~/.infra). Use BEFORE any task that touches servers, VMs, SSH access, networks, VPNs, DNS/domains, routers, firewalls, containers, services or home-lab devices — to look up addresses, access paths, dependencies and known issues — and AFTER every infra change or discovered drift to write reality back as current facts (edit in place; events go to `dotinfra event add`), then lint and sync.
---

# Infra CMDB: read first, write back

The CMDB is the shared memory of every human and agent working on this
infrastructure. Stale docs cause outages; treat updating it as part of the task.

## Locate it

- Root: `$DOTINFRA_ROOT`, else the nearest folder with `.dotinfra.toml`, else `~/.infra`.
- `dotinfra doctor` checks the installation. If `dotinfra` is missing, the files are
  still plain Markdown — read and edit them directly and tell the user.
- Its `AGENTS.md` holds the local rules; they override this skill where they differ.

## 1. Read before acting

1. Read `INDEX.md` (inventory: id, kind, status, address, role).
2. Read the file of every component you will touch, plus everything in its
   `depends_on`, `runs_on` and `ssh.jump`. `dotinfra show ID` prints one;
   `dotinfra ls --tag gpu --status active --json` filters.
3. Check `## Constraints & known issues` before diagnosing — the answer is often there.
4. Leave `events/` (the event log) alone unless the task is about what happened
   when: then `dotinfra event list --host ID [--since -30d]`.
5. Reach hosts the documented way: `ssh ID` works once the user has run
   `dotinfra ssh-config` (it writes `ProxyJump` from `ssh.jump`).

## 2. File routing

| what | folder | example id |
|---|---|---|
| a machine you log into (VM, VPS, NAS, SBC, laptop) | `servers/` | `nas` |
| LAN, VLAN, VPN overlay | `networks/` | `wireguard` |
| domain + DNS zone | `domains/` | `example.com` |
| gateway, firewall, AP with a management UI | `routers/` | `router` |
| software running on a server (`runs_on:`) | `services/` | `home-assistant` |
| anything else with an address or a warranty | `devices/` | `ups` |

One component per file, file stem = id (`[a-z0-9][a-z0-9._-]*`). Create new ones
with `dotinfra new KIND ID [--title T] [--address A]` — never invent a new folder.
Files ending `.local.md` are device-private and never synced.

## 3. Schema (frontmatter)

```yaml
---
id: gpu1                     # optional, defaults to file stem
status: active               # REQUIRED: active | planned | degraded | retired
role: Local LLM inference    # one line
tags: [fleet, gpu]           # fleet = shown on the fleet dashboard
address: 10.10.0.21          # primary IP/hostname (also the metrics address)
os: Ubuntu 24.04 LTS
ssh:                         # one-level map: user, host, port, jump, key
  user: alice
  jump: hub                  # id of the jump-host component; host defaults to address
metrics: [node:9100, dcgm:9400]      # Prometheus job:port at address
secrets: [gpu1_sudo]         # vault KEY NAMES only
depends_on: [nas]            # component ids
runs_on: nas                 # services only
url: http://10.10.0.40:8123
facts:                       # map written by `dotinfra drift --update`; do not hand-edit
updated: 2026-09-26          # set to today whenever you reconcile the doc
---
```

Only this YAML subset parses: scalars, inline lists `[a, b]`, `- item` block
lists, one-level maps. No multi-line strings, no nested maps, no lists of maps.

## 4. Documents state what IS

A component file is a **fact sheet of the current state**. Agents load these
files on every infra task, so every line costs context: a doc must be concise,
current and cheap to read. History does not belong in it.

Body sections (H2; keep existing names and order — sync merges per section):

| section | content |
|---|---|
| `Overview` | 2–3 lines: what it is, where, who relies on it |
| `Access` | how to reach it (ssh, UI, console fallback), vault key names |
| `Configuration` (or `Hardware`, `Services`) | the facts someone acts on: paths, ports, versions, commands |
| `Constraints & known issues` | limits and open problems; remove an issue once resolved |

Length: ≈ ≤ 40 lines for a simple component, ≤ 80 for a complex one.
`dotinfra lint` warns `journal` (a History/Changelog/Log section, or more than
5 lines starting with a date) and `long` (body over `[lint] max_lines`).

## 5. Write back in the same turn

After any change you made or discovered (package installed, port opened,
service moved, host renamed, disk failing, credential rotated):

1. Update frontmatter facts that changed; set `updated:` to today.
2. **Edit the prose in place**: rewrite the line that is no longer true, delete
   what no longer exists, remove resolved issues. Never append a dated note.
3. Record the event, if it is worth remembering, in the event log — not in the doc:
   `dotinfra event add --host ID --type change "raised ZFS ARC limit to 16 GB"`
   (types: `outage`, `incident`, `maintenance`, `change`, `observation`;
   `--time -2h`, `--end` for durations). Git history keeps old doc versions.
4. Touched several components? Update each one (and the dependency edges).
5. Retiring something: `status: retired` + an event. Never delete the file.
6. Unverified or suspicious observations go under `## Constraints & known issues`, not into facts.

If reality contradicts the doc: reality wins. Fix the doc (or
`dotinfra drift ID --update` for probed facts); log notable drift with
`dotinfra event add --type observation`. If the doc describes *intended* state
and the host is wrong, ask the user before changing the host.

### Cleaning up a journal-style doc

When lint reports `journal` or `long` (typical after upgrading from dotinfra
< 0.3): fold anything still true from the History lines into the sections as
facts, move the notable past events into the log with `dotinfra event add
--time YYYY-MM-DD ...` (skip trivia), delete the History section and resolved
issues, and cut detail nobody acts on. Keep every current fact.

## 6. Check and sync

```sh
dotinfra lint            # must exit 0; fix every error, read the warnings
dotinfra index           # after adding/renaming/retiring components
dotinfra sync            # commit + exchange with other devices + push
```

`dotinfra sync` exit code 2 = merge conflict → use the `infra-sync` skill.
Any command exiting 3 = this dotinfra is older than the CMDB needs → `dotinfra upgrade`.
Machine-specific settings go in `.dotinfra.local.toml` (untracked), never in `.dotinfra.toml`.
Lint errors about secret-looking content → use the `infra-vault` skill; never
silence them with `dotinfra:allow-secret` unless the user confirms it is not a secret.

## Rules that are never negotiable

- No secret values in any CMDB file, commit message or chat — key names only.
- Never `rsync --delete` or copy files between CMDB clones; only `dotinfra sync`.
- `INDEX.md` is generated; edit component files instead.
- Do not reorder or rename H2 headings of existing files (except when
  converting a journal-style doc, above).
- Docs hold the current state; history goes to `dotinfra event add`.
