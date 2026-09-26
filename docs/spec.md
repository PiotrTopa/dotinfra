# dotinfra — design spec (implementation contract)

This file is the contract that every module, template, skill, doc and example in
this repository follows. When the code and this spec disagree, fix one of them in
the same change.

## 1. What dotinfra is

`dotinfra` turns a folder of Markdown files (by default `~/.infra/`) into a
**self-maintaining infrastructure CMDB** that humans and AI coding agents share:

- one Markdown file per component (server, network, domain, router, service, device),
  with a small **YAML frontmatter** block for machine-readable facts and free prose below;
- **agent rules** (`AGENTS.md` + bundled Agent Skills) that make every agent
  *read the CMDB first* and *write reality back* after each change;
- a **secret vault** so docs reference secret *keys*, never values;
- **git-based sync** between devices, with section-aware **reconciliation** of conflicts;
- **generators** for things derived from the CMDB: SSH config, Prometheus targets,
  a Grafana fleet dashboard, an inventory index;
- an optional **monitoring bundle** (Prometheus + Grafana + Pushgateway) wired to those generators.

Principles: plain files first (the CMDB stays useful with no tool installed);
zero runtime dependencies (Python ≥ 3.11 stdlib only; `git`, `ssh`, optional `age`);
generated artifacts are reproducible; nothing secret is ever written to the CMDB.

## 2. CMDB layout (what `dotinfra init` creates)

```
~/.infra/
├── .dotinfra.toml        # tool config (section 5)
├── .gitignore            # ignores .dotinfra/state/, *.local.md, vault.json
├── .gitattributes        # "*.md merge=dotinfra" (section 7), text=auto eol=lf, vault.age binary
├── README.md             # human intro + the rules (from template)
├── AGENTS.md             # rules for AI agents (from template) — canonical
├── CLAUDE.md             # one line: "@AGENTS.md" (Claude Code import)
├── INDEX.md              # generated inventory (dotinfra index)
├── servers/  networks/  domains/  routers/  services/  devices/
└── .dotinfra/state/      # local, untracked: sync logs, last-probe facts
```

Folder ↔ kind mapping: `servers/→server`, `networks/→network`, `domains/→domain`,
`routers/→router`, `services/→service`, `devices/→device`. Any `*.md` in these
folders is a component. Files at the root (README, AGENTS, CLAUDE, INDEX) are not.
Files ending in `.local.md` are ignored by git and by the loader.

## 3. Component file format

```markdown
---
id: gpu1
kind: server
title: gpu1 — GPU inference node
status: active
role: GPU inference, Ollama
tags: [fleet, gpu]
address: 10.10.0.20
os: Debian 12
ssh:
  user: alice
  host: 10.10.0.20
  port: 22
  jump: hub
metrics: [node:9100, dcgm:9400]
secrets: [gpu1_sudo]
depends_on: [nas]
updated: 2026-09-23
---

# gpu1

## Overview
...
## Configuration
...
## Access
...
## Secrets
...
## Known issues
...
## History
...
```

### 3.1 Frontmatter syntax (YAML subset)

Parsed by dotinfra's own parser (`dotinfra.frontmatter`), no PyYAML. Supported:

- `key: scalar` — scalar is a string; quotes `"..."`/`'...'` are stripped; `true/false` → bool;
  integers → int; `null`/`~`/empty → None. Dates stay strings (`2026-09-23`).
- `key: [a, b, "c d"]` — inline list of scalars.
- block list: `key:` followed by lines `  - item` (scalars only).
- one-level map: `key:` followed by indented `  sub: scalar` or `  sub: [inline list]`.
- `# comments` on their own line, and ` # trailing` comments after unquoted scalars.

Anything else (multi-line strings, anchors, nested maps deeper than one level,
lists of maps) is a **parse error** with file:line. `dump()` writes the same subset
back deterministically, preserving key order of the input dict.

### 3.2 Fields

| field | type | required | meaning |
|---|---|---|---|
| `id` | str `[a-z0-9][a-z0-9._-]*` | no (defaults to file stem, lowercased) | unique across the CMDB |
| `kind` | `server\|network\|domain\|router\|service\|device` | no (derived from folder) | must match folder if given |
| `title` | str | no (defaults to first `# H1`, else id) | display name |
| `status` | `active\|planned\|degraded\|retired` | **yes** | lifecycle |
| `role` | str | recommended | one-line purpose |
| `tags` | list[str] | no | free labels; `fleet` = compute boxes shown on the dashboard |
| `address` | str | no | primary IP/hostname |
| `os` | str | no | |
| `ssh` | map: `user, host, port, jump, key` | no | `host` defaults to `address`; `jump` is another component **id** |
| `metrics` | list[`job:port`] | no | Prometheus scrape targets at `address` |
| `secrets` | list[str] | no | vault keys this component needs |
| `depends_on` | list[id] | no | ids of other components |
| `runs_on` | id | no (services) | the server hosting the service |
| `url` | str | no | web UI / endpoint |
| `facts` | map | no | written by `dotinfra drift --update`; last probed facts |
| `updated` | `YYYY-MM-DD` | recommended | last time the doc was reconciled with reality |

Unknown keys are allowed (warning only with `lint --strict`).

### 3.3 Body conventions

Recommended H2 sections (templates contain them): Overview, Configuration, Access,
Secrets, Known issues, History. `History` is an append-only, newest-first bullet
list of dated entries (`- 2026-09-23 — upgraded NVIDIA driver to 615`). The
reconciler (section 7) relies on H2 sections as merge units.

## 4. Python package layout

```
src/dotinfra/
  __init__.py        __version__ = "0.1.0"
  __main__.py        python -m dotinfra
  cli.py             argparse entry point `main(argv=None) -> int`
  context.py         Context (root, config, components(), secret())
  config.py          find_root(), load_config()
  frontmatter.py     parse(text)->(meta, body), dump(meta)->str, FrontmatterError
  model.py           Component, load_cmdb(root)
  scaffold.py        init, new
  lint.py            lint rules
  index.py           INDEX.md generator
  sshconfig.py       ssh config generator
  vault.py           vault backends + CLI
  sync.py            sync, status, peers, timer install
  reconcile.py       section-aware 3-way merge + git merge driver
  drift.py           ssh fact probe vs frontmatter
  skills.py          install bundled skills
  monitoring.py      prometheus file_sd + monitoring bundle render   (lane B)
  grafana.py         fleet dashboard generator + push via API          (lane B)
  events.py          Grafana annotation events                        (lane B)
  templates/         component templates + scaffold files (package data)
  skills/            -> bundled Agent Skills (package data; copy of /skills)
```

Tests: `tests/test_*.py`, **stdlib `unittest`** only, runnable with
`python -m unittest discover -s tests`. Tests must not touch `~`, the network or
real hosts (use temp dirs; set `DOTINFRA_ROOT`, `HOME` in env for subprocesses).

### 4.1 Core API (stable, used across modules)

```python
# __init__.py
class DotinfraError(Exception)    # expected failures; the CLI prints "dotinfra: error: ..." and exits 1

# config.py
DEFAULT_ROOT = Path("~/.infra").expanduser()
def find_root(start: Path | None = None) -> Path
    # order: $DOTINFRA_ROOT; walk up from start/cwd for .dotinfra.toml; DEFAULT_ROOT
@dataclass
class Config:
    root: Path
    data: dict                       # parsed .dotinfra.toml (defaults merged in)
    def get(self, section: str, key: str, default=None)
def load_config(root: Path) -> Config

# model.py
KINDS = {"servers": "server", "networks": "network", "domains": "domain",
         "routers": "router", "services": "service", "devices": "device"}
@dataclass
class Component:
    id: str
    kind: str
    path: Path            # absolute
    meta: dict            # frontmatter as parsed (id/kind/title filled with defaults)
    body: str             # markdown after frontmatter
    @property title -> str; status -> str|None; tags -> list[str]; address -> str|None
    @property metrics -> list[tuple[str, int]]   # [("node", 9100), ...]
    def rel(self) -> str  # path relative to root, posix
def load_cmdb(root: Path, *, strict: bool = False) -> list[Component]
    # sorted by (kind, id); files that fail to parse raise FrontmatterError if strict,
    # otherwise are skipped and recorded in load_cmdb.errors (list[str]) — see lint
def by_id(components) -> dict[str, Component]

# context.py
@dataclass
class Context:
    root: Path
    config: Config
    def components(self) -> list[Component]      # cached
    def component(self, id: str) -> Component    # DotinfraError if unknown
    def secret(self, key: str) -> str            # via vault backend in config
def get_context(args, *, require=True) -> Context   # honours args.root; DotinfraError if no .dotinfra.toml (unless require=False)

# vault.py
def open_vault(config: Config) -> Vault          # Vault.get/set/delete/keys
```

### 4.2 CLI registration

`cli.py` builds the parser with a global `--root PATH` option and subcommands.
Lane-B modules expose `register(subparsers) -> None`; `cli.py` calls
`monitoring.register`, `grafana.register`, `events.register`. Every subcommand
sets `func=handler` where `handler(args) -> int` (exit code); handlers obtain
state through `get_context(args)`.

## 5. `.dotinfra.toml`

```toml
[cmdb]
name = "home"                   # shown in INDEX.md and dashboards
device = ""                     # this device's name for sync commit messages; "" = hostname

[vault]
backend = "file"                # "file" | "age"
path = "~/.config/dotinfra/vault.json"   # file backend (mode 0600, outside the repo)
age_file = "vault.age"          # age backend: path relative to CMDB root (safe to commit)
age_identity = "~/.config/dotinfra/age.key"
age_recipients = []             # public keys; the identity's own key is added automatically

[sync]
remote = "origin"               # hub remote; "" = peers only
peers = []                      # other git remote names to exchange with (ssh peers)
auto_commit = true
branch = "main"

[monitoring]
prometheus_url = "http://localhost:9090"
grafana_url = "http://localhost:3000"
grafana_user = "admin"
grafana_password_key = "grafana_password"   # vault key
bundle_dir = "~/dotinfra-monitoring"        # where `monitoring render` writes
```

## 6. CLI surface

```
dotinfra init [PATH] [--name N] [--no-git] [--skills none|claude|agents|both] [--example [NAME]]
dotinfra new KIND ID [--title T] [--address A]      # from templates/KIND.md, opens nothing
dotinfra ls [--kind K] [--tag T] [--status S] [--json]
dotinfra show ID [--json]
dotinfra lint [--strict] [--json]        # exit 1 on errors
dotinfra index [--check]                 # rewrite INDEX.md; --check exits 1 if stale
dotinfra ssh-config [--output FILE]      # Host blocks with ProxyJump from ssh.jump
dotinfra vault list|get KEY|set KEY|rm KEY|exec KEY -- CMD...
dotinfra vault import FILE [--overwrite]           # flat JSON {key: secret}, e.g. legacy vaults
dotinfra vault migrate --to age|file [--force] [--remove-plaintext]
dotinfra vault rekey                               # re-encrypt vault.age to current recipients
dotinfra sync [--no-push] [--dry-run] [--message M]   # exit 0 ok, 1 remote failed, 2 conflict
dotinfra status                          # dirty files, ahead/behind per remote, conflicts
dotinfra peer add NAME SSH_URL | peer ls | peer rm NAME
dotinfra reconcile [--continue] [--abort]
dotinfra merge-driver BASE OURS THEIRS PATH   # git merge driver entry point (internal)
dotinfra timer install|remove [--interval 15m]   # systemd --user timer, cron fallback printed
dotinfra drift [ID...] [--update] [--json]
dotinfra skills install [--target claude|agents|both] [--link]
dotinfra doctor
# lane B
dotinfra monitoring targets [--output DIR]     # Prometheus file_sd JSON, one file per job
dotinfra monitoring render [--output DIR]      # full bundle: compose + prometheus + grafana provisioning + targets + dashboard
dotinfra grafana dashboard [--output FILE]     # fleet dashboard JSON
dotinfra grafana push [--file FILE]            # upload via API (password from vault)
dotinfra event add --host ID --type T [--time T] TEXT
dotinfra event list [--host ID] [--type T] [--limit N]
```

## 7. Sync & reconciliation

**Model.** The CMDB is a git repo on branch `main`. Devices exchange commits through
a **hub** remote (a private GitHub/Gitea repo or a bare repo on any SSH host) and/or
directly with **peers** (other devices' CMDBs over SSH, `ssh://host/~/.infra`).
Never `rsync --delete` between copies: it silently discards the other side's edits.

**`dotinfra sync`** (idempotent, safe to run from a timer):
1. If the tree is dirty and `auto_commit`: `git add -A` and commit with
   `sync(<device>): <n> file(s): <comma-separated rel paths, truncated>`.
2. For each of `[remote] + peers` that exists: `git fetch`.
3. Integrate each fetched `<remote>/<branch>` with `git merge --no-edit` (merge,
   not rebase — history of both devices is preserved and the merge driver runs).
   Fast-forwards when possible.
4. On conflict: run the reconciler over conflicted files (the merge driver usually
   already handled `.md` files). If conflicts remain → leave the repo in merge
   state, write `.dotinfra/state/RECONCILE.md` listing files and conflict blocks,
   exit code 2, and print next steps (`dotinfra reconcile --continue` after editing).
5. If clean: regenerate `INDEX.md` if stale (commit it as `index: regenerate`).
   A conflicted `INDEX.md` is never hand-merged: it is regenerated.
6. Push `main` to the hub remote (not to peers — peers pull; pushing into
   a non-bare peer's checked-out branch is refused by git). `--no-push` skips.
   A fetch or push failure is reported and gives exit code 1.
A lock file `.dotinfra/state/sync.lock` prevents concurrent runs (stale after 10 min).

**Merge driver** (`.gitattributes: *.md merge=dotinfra`; `dotinfra init` and
`dotinfra sync` ensure `git config merge.dotinfra.driver "<python> -m dotinfra merge-driver %O %A %B %P"`,
using the absolute path of the interpreter running dotinfra so the driver works even
when `dotinfra` is not on git's PATH; every sync re-points it after upgrades).
Section-aware 3-way merge of one component file:
- **Frontmatter**: per key 3-way. Changed on one side only → take it. Changed on
  both sides to the same value → take it. Both changed differently → for lists,
  union preserving order (ours first), minus items one side removed from the base;
  for `updated`, max; for scalars/maps → conflict. Keys whose merged value equals
  ours keep ours' raw lines, so frontmatter comments survive.
- **Body**: split into preamble + H2 sections (`## Heading`), keyed by heading text.
  Per section 3-way: one side changed → take it; both changed identically → take it;
  section added on one side → keep it (in that side's position); deleted on one side
  and unchanged on the other → delete; `History` sections (heading matching
  `/^history|changelog|log$/i`) → union of bullet lines (with their indented
  continuation lines), de-duplicated, minus entries one side deleted, sorted
  newest-first by leading date (same day: entries new since the base first, undated
  entries last); a section deleted on one side and modified on the other → conflict;
  headings inside code fences are not section boundaries; other both-changed sections → try a line-level
  `git merge-file` on just that section; if still conflicting → keep conflict markers
  inside that section only.
- Exit 0 when clean (write result to OURS path), 1 when conflict markers remain.

**`dotinfra reconcile`**: shows remaining conflicts (exit 2 while any remain);
`--continue` verifies no markers remain, runs lint (errors in the reconciled files
block the commit), commits the merge (`reconcile(<device>): ...`) and then resumes
`dotinfra sync` (merging any remaining remotes and pushing); `--abort` runs
`git merge --abort`. A sync started while a merge is unresolved exits 2 without
touching anything.

## 8. Vault

Docs reference keys only. Backends:
- **file**: JSON `{key: secret}` at `vault.path` (default outside the repo), mode 0600,
  compatible with a legacy flat JSON vault file via `vault import`.
- **age**: the whole vault encrypted with `age` into `vault.age` inside the repo (so it
  syncs with the CMDB). Decrypt with `age_identity`; encrypt to identity + recipients.
  Requires the `age` binary. Each device has its own identity, and adding a
  device means adding its public key to `age_recipients` and re-encrypting (`vault rekey`).

`set` reads via `getpass` (never argv). `exec KEY -- CMD` pipes the secret +
newline to CMD's stdin. `get` prints to stdout. Secrets are never logged.

## 9. Lint rules

Errors: frontmatter parse error; missing/invalid `status`; bad `id` format; duplicate
id; `kind` mismatches folder; `ssh.jump`/`depends_on`/`runs_on` referencing an
unknown id; malformed `metrics` entry; **secret-looking content** in any tracked file
(`-----BEGIN .*PRIVATE KEY-----`, `password\s*[:=]\s*\S+` not followed by a vault
reference — i.e. the rest of the line does not mention `vault` and the value is not a
`<placeholder>` or `***` — AWS `AKIA[0-9A-Z]{16}`, `ghp_[A-Za-z0-9]{36}`, `sk-[A-Za-z0-9]{20,}`,
`xox[baprs]-`), unless the line contains `dotinfra:allow-secret`.
Warnings: missing `role`; missing `updated`, or older than 180 days (`stale`); no H1;
secret key in `secrets` not present in the vault (only when the vault is readable); unknown keys (`--strict`).

## 10. Drift

`dotinfra drift ID` runs one SSH command (through `ssh.jump` if set) that prints
`hostname`, `uname -srm`, OS pretty name, CPU count, total memory, and primary
IPv4 addresses, portable across Linux/FreeBSD/Termux/postmarketOS (POSIX `sh`,
tolerate missing tools). It compares them with `os`, `address`, `facts.*` and reports
drift (`os` drifts when a word of the documented value is missing from the probed
OS name; `address` when it is an IPv4 literal not among the probed addresses; each
recorded `facts.*` value that changed). `--update` writes `facts:` (hostname, kernel,
arch, cpus, mem_gb, ips, probed) into frontmatter, replaces a drifted `os` with the
probed name, and bumps `updated`; other lines and comments are left untouched.
Results cached in `.dotinfra/state/facts/ID.json`. Without IDs, every component with
`ssh:` whose status is neither `planned` nor `retired` is probed. Exit 1 if anything
drifted or was unreachable.

## 11. Agent Skills (repo `skills/`, installed by `dotinfra skills install`)

Standard Agent Skills layout (`skills/<name>/SKILL.md` with `name` + `description`
frontmatter), usable by Claude Code (`~/.claude/skills`) and other agents that
read `~/.agents/skills`:
- `infra-cmdb` — read-first / write-back workflow, file routing, schema, commit + sync.
- `infra-vault` — secret handling rules and commands.
- `infra-sync` — sync, conflict reconciliation procedure for agents.
- `infra-onboard` — guided bootstrap: interview the user, discover hosts, create the CMDB.
- `infra-monitoring` — monitoring bundle, dashboards, event annotations.
