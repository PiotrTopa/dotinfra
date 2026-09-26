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
├── .dotinfra.toml        # shared tool config (section 5)
├── .dotinfra.local.toml  # optional, untracked: this device's overrides (section 5.1)
├── .gitignore            # managed: ignores .dotinfra/state/, .dotinfra.local.toml, *.local.md, vault.json
├── .gitattributes        # managed: "*.md merge=dotinfra" (section 7), text=auto eol=lf, vault.age binary
├── README.md             # managed: "Start here — new machine", layout, the rules
├── AGENTS.md             # managed: rules for AI agents — canonical
├── CLAUDE.md             # managed: "@AGENTS.md" (Claude Code import)
├── INDEX.md              # generated inventory (dotinfra index)
├── .claude/skills/  .agents/skills/   # optional project-scope Agent Skills (section 11)
├── servers/  networks/  domains/  routers/  services/  devices/
└── .dotinfra/state/      # local, untracked: sync logs, last-probe facts
```

"Managed" files keep dotinfra's content between markers (section 12); text
outside the markers belongs to the user.

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
| `labels` | map | no | extra Prometheus target labels; `host` overrides the id in `host`/`instance`; `job`/`instance` reserved |
| `secrets` | list[str] | no | vault keys this component needs |
| `depends_on` | list[id] | no | ids of other components |
| `runs_on` | id | no (services) | the server hosting the service |
| `url` | str | no | web UI / endpoint (for the monitoring service: Grafana) |
| `prometheus_url` | str | no | monitoring service only: Prometheus URL (default `http://<address>:9090`) |
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
  __init__.py        __version__, DotinfraError
  __main__.py        python -m dotinfra
  cli.py             argparse entry point `main(argv=None) -> int`, doctor
  context.py         Context (root, config, components(), secret()); runs the version guard
  config.py          find_root(), load_config() (shared + local), TOML line editing
  versioning.py      version parsing, min_version guard (exit 3)
  managed.py         dotinfra:managed blocks: find, wrap, refresh, adopt 0.1.x files
  migrate.py         `migrate`: schema migration registry, managed blocks, skills
  upgrade.py         `upgrade`: install-method detection, GitHub release check
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
  skills.py          agent target table, detection, install (user/project scope), records
  monitoring.py      prometheus file_sd + monitoring bundle render   (lane B)
  grafana.py         fleet dashboard generator + push via API          (lane B)
  events.py          Grafana annotation events                        (lane B)
  templates/         component templates + managed-file templates (package data)
  templates/legacy/  0.1.x renders of the managed files, for `migrate` to recognise
  skills/            -> bundled Agent Skills (package data; copy of /skills)
```

Tests: `tests/test_*.py`, **stdlib `unittest`** only, runnable with
`python -m unittest discover -s tests`. Tests must not touch `~`, the network or
real hosts (use temp dirs; set `DOTINFRA_ROOT`, `HOME` in env for subprocesses).

### 4.1 Core API (stable, used across modules)

```python
# __init__.py
class DotinfraError(Exception)    # expected failures; the CLI prints "dotinfra: error: ..." and exits
                                  # with the exception's `exit_code` attribute (default 1)

# config.py
DEFAULT_ROOT = Path("~/.infra").expanduser()
def find_root(start: Path | None = None) -> Path
    # order: $DOTINFRA_ROOT; walk up from start/cwd for .dotinfra.toml; DEFAULT_ROOT
@dataclass
class Config:
    root: Path
    data: dict                       # parsed .dotinfra.toml (defaults merged in)
    def get(self, section: str, key: str, default=None)
def load_config(root: Path, *, local: bool = True) -> Config
    # DEFAULTS <- .dotinfra.toml <- .dotinfra.local.toml (deep merge of tables)

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
    # version guard: args.version_guard = "enforce" (default) | "warn" | "off"

# versioning.py
class VersionTooOld(DotinfraError)  # exit_code = 3
def installed_version() -> str; def is_newer(required, installed=None) -> bool
def minor_floor(version=None) -> str   # "0.2.7" -> "0.2.0"

# monitoring.py
def monitoring_endpoints(ctx, *, warn=True, need=("grafana", "prometheus"))
    -> tuple[str, str, str | None]    # (grafana_url, prometheus_url, host component id)

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
schema = 1                      # CMDB layout version (section 12); absent = 0 (0.1.x)
min_version = "0.2.0"           # oldest dotinfra allowed to write here (section 12)
# device = ""                   # per device, in .dotinfra.local.toml; "" = hostname

[vault]
backend = "file"                # "file" | "age"
path = "~/.config/dotinfra/vault.json"   # file backend (mode 0600, outside the repo)
age_file = "vault.age"          # age backend: path relative to CMDB root (safe to commit)
age_identity = "~/.config/dotinfra/age.key"
age_recipients = []             # public keys of every device; `vault identity`/`migrate` add this device's

[sync]
remote = "origin"               # hub remote; "" = peers only
remote_url = ""                 # clone URL shown in README.md (init --remote, or migrate from git)
peers = []                      # other git remote names to exchange with (ssh peers)
auto_commit = true
branch = "main"

[monitoring]
service = "monitoring"          # component id of the monitoring service; its runs_on = the host
# grafana_url / prometheus_url  # explicit overrides; otherwise derived (section 13)
grafana_user = "admin"
grafana_password_key = "grafana_password"   # vault key
bundle_dir = "~/dotinfra-monitoring"        # where `monitoring render` writes
role = "client"                 # per device, in .dotinfra.local.toml: "server" | "client"

[skills]
project = []                    # targets installed at project scope inside the CMDB (section 11)
```

### 5.1 `.dotinfra.local.toml`

Optional, untracked (ignored by the managed `.gitignore`), deep-merged over
`.dotinfra.toml` on its own device only. It is the place for everything
machine-specific: `[cmdb] device`, vault paths, `[monitoring] role`,
`bundle_dir`, and URL overrides (e.g. Grafana reached through a VPN address).
Commands that record per-device state (`monitoring setup-server`) write here;
commands that record shared state (`peer add`, `vault identity`, `migrate`)
write to `.dotinfra.toml`.

## 6. CLI surface

```
dotinfra init [PATH] [--name N] [--no-git] [--example [NAME]] [--remote URL]
              [--skills LIST|auto|all|none] [--skills-scope user|project|both] [--link] [--yes]
dotinfra new KIND ID [--title T] [--address A]      # from templates/KIND.md, opens nothing
dotinfra ls [--kind K] [--tag T] [--status S] [--json]
dotinfra show ID [--json]
dotinfra lint [--strict] [--json]        # exit 1 on errors
dotinfra index [--check]                 # rewrite INDEX.md; --check exits 1 if stale
dotinfra ssh-config [--output FILE]      # Host blocks with ProxyJump from ssh.jump
dotinfra vault list|get KEY|set KEY|rm KEY|exec KEY -- CMD...
dotinfra vault import FILE [--overwrite]           # flat JSON {key: secret}, e.g. legacy vaults
dotinfra vault migrate --to age|file [--force] [--remove-plaintext]
dotinfra vault identity                            # age: create this device's identity if missing, record + print public key
dotinfra vault rekey                               # re-encrypt vault.age to current recipients
dotinfra sync [--no-push] [--dry-run] [--message M]   # exit 0 ok, 1 error/remote failed, 2 conflict, 3 too old
dotinfra status                          # dirty files, ahead/behind per remote, conflicts
dotinfra peer add NAME SSH_URL | peer ls | peer rm NAME
dotinfra reconcile [--continue] [--abort]
dotinfra merge-driver BASE OURS THEIRS PATH   # git merge driver entry point (internal)
dotinfra timer install|remove [--interval 15m]   # systemd --user timer, cron fallback printed
dotinfra drift [ID...] [--update] [--json]
dotinfra skills install [--target LIST|auto|all|both] [--scope user|project|both] [--link]
dotinfra skills status
dotinfra migrate [--dry-run] [--yes]     # section 12
dotinfra upgrade [--check] [--pre]       # section 12
dotinfra doctor [--check-updates]
# lane B
dotinfra monitoring targets [--output DIR] [--stdout] [--force]   # Prometheus file_sd JSON, one file per job
dotinfra monitoring render [--output DIR] [--force]     # full bundle: compose + prometheus + grafana provisioning + targets + dashboard
dotinfra monitoring where [--check] [--timeout S]       # service, host, URLs, this device's role (section 13)
dotinfra monitoring setup-server [--bundle-dir DIR] [--force]   # role = server locally + render
dotinfra grafana dashboard [--output FILE]              # fleet dashboard JSON
dotinfra grafana push [--file FILE] [--folder TITLE] [--home]   # upload via API (credentials from vault)
dotinfra event add --host ID --type T [--time T] [--end T] TEXT
dotinfra event list [--host ID] [--type T] [--since T] [--limit N] [--json]
dotinfra event rm ID
```

Every command prints expected failures as `dotinfra: error: <message>` on stderr and
exits 1 (3 for the version guard, section 12); only bugs produce tracebacks.

## 7. Sync & reconciliation

**Model.** The CMDB is a git repo on branch `main`. Devices exchange commits through
a **hub** remote (a private GitHub/Gitea repo or a bare repo on any SSH host) and/or
directly with **peers** (other devices' CMDBs over SSH, `ssh://host/~/.infra`).
Never `rsync --delete` between copies: it silently discards the other side's edits.

**`dotinfra sync`** (idempotent, safe to run from a timer):
1. If the tree is dirty and `auto_commit`: `git add -A` and commit with
   `sync(<device>): <n> file(s): <comma-separated rel paths, truncated>`.
2. For each of `[remote] + peers` that exists: `git fetch`.
3. **Version guard**: for each fetched `<remote>/<branch>` with new commits, read
   `.dotinfra.toml` from that ref (`git show ref:.dotinfra.toml`); if its
   `[cmdb] min_version` is newer than the running dotinfra, merge nothing, keep the
   local commit, log it and exit **3** (no push).
4. Integrate each fetched `<remote>/<branch>` with `git merge --no-edit` (merge,
   not rebase — history of both devices is preserved and the merge driver runs).
   Fast-forwards when possible.
5. On conflict: run the reconciler over conflicted files (the merge driver usually
   already handled `.md` files). If conflicts remain → leave the repo in merge
   state, write `.dotinfra/state/RECONCILE.md` listing files and conflict blocks,
   exit code 2, and print next steps (`dotinfra reconcile --continue` after editing).
6. If clean: regenerate `INDEX.md` if stale (commit it as `index: regenerate`).
   A conflicted `INDEX.md` is never hand-merged: it is regenerated. On the
   monitoring host (`[monitoring] role = "server"`), rewrite the Prometheus
   file_sd targets in `<bundle_dir>/targets` (a failure there is a warning only).
7. Push `main` to the hub remote (not to peers — peers pull; pushing into
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
  for `updated`, the later date (an emptied `updated` yields to the other side's);
  for scalars/maps → conflict. Keys whose merged value equals
  ours keep ours' raw lines, so frontmatter comments survive.
- **Body**: split into preamble + H2 sections (`## Heading`), keyed by heading text.
  Per section 3-way: one side changed → take it; both changed identically → take it;
  section added on one side → keep it (in that side's position); deleted on one side
  and unchanged on the other → delete; `History` sections (heading matching
  `/^history|changelog|log$/i`) → union of bullet lines (with their indented
  continuation lines), de-duplicated, minus entries one side deleted, sorted
  newest-first by leading date (same day: entries new since the base first, undated
  entries last); a section deleted on one side and modified on the other → conflict;
  headings inside code fences are not section boundaries; other both-changed sections:
  if both sides only *added* lines (no base line deleted or changed), keep every
  addition, ours first where both added at the same spot; otherwise try a line-level
  `git merge-file` on just that section; if still conflicting → keep conflict markers
  inside that section only.
- Exit 0 when clean (write result to OURS path), 1 when conflict markers remain.
- Content the driver cannot handle (not valid UTF-8, an I/O error) falls back to
  `git merge-file` on the whole file, so the driver never fails harder than git alone.

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
  Requires the `age` binary. Each device has its own identity; `vault identity`
  creates it and records its public key in `age_recipients` (the full device set,
  synced with the CMDB; `migrate` and `rekey` record this device's key too).
  Adding a device: `vault identity` + sync there, `vault rekey` + sync on a device
  that can decrypt, sync there again.

`set` reads via `getpass` (never argv). `exec KEY -- CMD` pipes the secret +
newline to CMD's stdin. `get` prints to stdout. Secrets are never logged.

## 9. Lint rules

Errors: frontmatter parse error; missing/invalid `status`; bad `id` format; duplicate
id; `kind` mismatches folder; `ssh.jump`/`depends_on`/`runs_on` referencing an
unknown id; malformed `metrics` entry; an `address` or `ssh.*` value that starts with
`-` or contains whitespace/control characters (`unsafe`: it would become an ssh option
or an ssh_config directive — `ssh-config` skips such components and `drift` refuses
them); **secret-looking content** in any tracked file, unless the line contains
`dotinfra:allow-secret` (at most one password error per line):

- `-----BEGIN .*PRIVATE KEY( BLOCK)?-----`, `AGE-SECRET-KEY-1...`, AWS
  `AKIA[0-9A-Z]{16}`, GitHub `gh[pousr]_[A-Za-z0-9]{36,}` / `github_pat_...`,
  `sk-[A-Za-z0-9_-]{20,}`, `xox[baprs]-`;
- `password\s*[:=]\s*\S+`, unless the value is a reference value or the rest of the
  line mentions `vault` or quotes a reference value, such as a quoted `~/...` path;
- **credential notation**: a backticked or quoted value directly after a credential
  word — `pass`, `passwd`, `password`, `pwd`, `passphrase`, `pin`, `token`, `secret`,
  `api key` (also `api_key`/`api-key`), case-insensitive, a whole word not preceded by
  a word character or a quote (so not `passwordless`, `PasswordAuthentication`,
  `grafana_password`, or a quoted `password` field name), optionally in `**bold**` —
  with `:`, `=`, `is` or `set to` in between. The separator is optional after
  `password`, `passwd`, `passphrase` and `pwd` (then whitespace is required) and
  required after the other words, which are everyday verbs and nouns ("pin X to",
  "pass --force"). JSON-style quoted keys (`"password": "..."`, `"api_token": "..."`)
  count too. Skipped when the value is a reference value or the rest of the line
  mentions `vault`.

A **reference value** is empty, a placeholder (starts with `<` or `{{`, or consists
only of `*`, `.`, `x`, `_`, `-`, `…`), a path or variable (starts with `~`, `/`, `./`,
`../`, `$`, `%`) or an `ALL_CAPS_NAME` containing an underscore.

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
probed name, and bumps `updated`; other lines and comments are left untouched. `os` comparison tolerates
point releases (`24.04` matches `24.04.1`).
Results cached in `.dotinfra/state/facts/ID.json`. Without IDs, every component with
`ssh:` whose status is neither `planned` nor `retired` is probed. Exit 1 if anything
drifted or was unreachable.

## 11. Agent Skills (repo `skills/`, installed by `dotinfra skills install`)

Standard Agent Skills layout (`skills/<name>/SKILL.md` with `name` + `description`
frontmatter):
- `infra-cmdb` — read-first / write-back workflow, file routing, schema, commit + sync.
- `infra-vault` — secret handling rules and commands.
- `infra-sync` — sync, conflict reconciliation procedure for agents.
- `infra-onboard` — guided bootstrap: interview the user, discover hosts, create the CMDB.
- `infra-monitoring` — monitoring topology, bundle, dashboards, event annotations.

Targets (`skills.TARGETS`; each path verified against the agent's docs, URL in the code):

| target | user scope | project scope |
|---|---|---|
| `claude` | `~/.claude/skills` | `.claude/skills` |
| `agents` (always) | `~/.agents/skills` | `.agents/skills` |
| `copilot` | `~/.agents/skills` | `.agents/skills` |
| `cline` | `~/.cline/skills` | `.claude/skills` |
| `antigravity` / `agy` | `~/.gemini/antigravity-cli/skills`, `~/.gemini/config/skills` | `.agents/skills` |
| `codex` | `~/.agents/skills` | `.agents/skills` |
| `gemini` | `~/.agents/skills` | `.agents/skills` |

Agents that document the shared `.agents/skills` directories are installed there
rather than into their own directory, so no agent sees a skill twice; a directory
shared by several targets is written once. `--target auto` (default) = `agents` +
every target whose config directory exists in `$HOME` or whose binary is on PATH.
Only the bundled skill directories are replaced; other skills are left alone;
unchanged skills are not rewritten. User-scope installs are recorded in
`$XDG_CONFIG_HOME/dotinfra/skills.json` (default `~/.config/dotinfra/`);
project-scope targets in `.dotinfra.toml` `[skills] project`. `dotinfra init`
installs both scopes for the chosen targets (asked on a TTY, `auto` otherwise) and
commits the project-scope copies with the initial layout. `skills status` and
`doctor` compare each installed skill's content hash with the package's.

## 12. Managed files, migrate, upgrade

**Managed blocks.** README.md, AGENTS.md, CLAUDE.md, .gitignore and .gitattributes
keep dotinfra's content between `<!-- dotinfra:managed:start v=X.Y.Z -->` /
`<!-- dotinfra:managed:end -->` (Markdown) or `# dotinfra:managed:start v=X.Y.Z` /
`# dotinfra:managed:end` (dotfiles). Refreshing replaces only what is between the
markers; the marker's `v=` changes only when the content does. A file without
markers (0.1.x) that equals a known 0.1.x render (`templates/legacy/*/`, `{{name}}`
matching any line) is replaced; otherwise the block is inserted on top, the user's
text is kept below (dotfiles: lines the block provides are dropped) and this is
reported.

**README "Start here — new machine"**: install command, `git clone <[sync] remote_url>
~/.infra` (a placeholder with instructions while unknown; credentials in http(s)
URLs are never written), `dotinfra doctor`, `dotinfra skills install` (and whether
the repo carries project-scope skills), vault access for the configured backend
with its configured paths (`[vault] path` for `file`; `age_file` and `age_identity`
for `age`), `dotinfra timer install`, the monitoring host (from the service
component), the minimum dotinfra version, and `.dotinfra.local.toml`. Managed
blocks are rendered from the shared `.dotinfra.toml` only (never
`.dotinfra.local.toml`: they are committed), so `migrate` refreshes the vault step
whenever `[vault]` changes there.

**`dotinfra migrate`**: (1) schema migrations `MIGRATIONS[n]: (toml_text, notes) ->
toml_text` from the CMDB's `[cmdb] schema` (absent = 0) up to the package's
`SCHEMA`; 0→1 writes `schema`/`min_version = "0.2.0"`, adds `[monitoring] service`
and comments out the literal 0.1 localhost URL defaults; (2) raise `min_version` to
the running release's `X.Y.0` (never lower it); (3) fill `[sync] remote_url` from
`git remote get-url <remote>` when empty; (4) refresh managed blocks; (5) refresh
project-scope skills and the recorded user-scope ones; (6) commit the changed
repository paths as `migrate: dotinfra X.Y.Z`. Idempotent; `--dry-run` prints the
plan; asks on a TTY unless `--yes`; refuses during a merge, on a newer schema, or
without a git identity (before writing anything).

**`dotinfra upgrade`**: pipx venv (`sys.prefix` under `pipx/venvs`) → `pipx upgrade
dotinfra`; user site → `python -m pip install --user -U git+https://github.com/PiotrTopa/dotinfra`;
other virtualenv → `python -m pip install -U git+...`; editable install or source
checkout → refused with a `git pull` hint; system → refused. `--pre` passes `--pre`.
Afterwards, inside a CMDB, runs `python -m dotinfra --root ROOT migrate --yes`.
`--check` only compares with the newest GitHub release tag (falls back to tags; 5 s
timeout; offline is not an error).

**Version guard**: `[cmdb] min_version` newer than the running version → exit 3,
`this CMDB needs dotinfra ≥ X (installed: Y); run dotinfra upgrade`. `ls`, `show`,
`skills status` and `upgrade` warn instead; `doctor` reports it as a FAIL row. `sync`
applies it to incoming refs (section 7).

## 13. Monitoring topology

The stack runs on one machine: the `runs_on` server of the component named by
`[monitoring] service`. `monitoring_endpoints(ctx)` resolves, per URL: explicit
`grafana_url` / `prometheus_url` (shared or local config) → the service component's
`url` / `prometheus_url` → `http://<address>:3000` / `:9090` with the service's
`address`, else its `runs_on` server's → `http://localhost:3000` / `:9090` with a
warning. Used by `grafana push`, `event`, `monitoring where` and `doctor`.

`[monitoring] role` (per device, default `client`): on `server`, a successful
`sync` rewrites the file_sd targets in `<bundle_dir>/targets`; on a client,
`monitoring render` / `targets` warn that the stack runs on `<host>` unless
`--output` or `--force` is given. `monitoring setup-server` writes `role = "server"`
(and `--bundle-dir`) to `.dotinfra.local.toml`, renders the bundle and prints the
`docker compose up -d` and `dotinfra timer install` steps. `monitoring render` and
`setup-server` also warn (stderr, never an error) when `docker` is on PATH and lists
containers (by name or image) or volumes named like `grafana`/`prometheus` outside the
bundle's compose project `dotinfra-monitoring`, unless `<bundle_dir>/docker-compose.override.yml`
exists: the warning points at "Adopting an existing stack" in the bundle README
(pin `GRAFANA_IMAGE` ≥ the running version, reuse volumes as `external:` in the
override). docker is asked with a 5 s timeout; any failure means no warning. `monitoring where` prints
service, host, both URLs, this device's role and, with `--check`, whether
`<grafana>/api/health` and `<prometheus>/-/ready` answer (3 s timeout).
