# Upgrading

A CMDB outlives any one dotinfra release, and several devices share it,
often running different versions. Three mechanisms keep this safe:
**managed blocks**, **`dotinfra migrate`** and the **version guard**.

## Short version

```sh
dotinfra upgrade          # new dotinfra, then `dotinfra migrate --yes` in the CMDB
dotinfra sync             # share the migration with the other devices
```

Then run `dotinfra upgrade` on every other device. A device that has not been
upgraded yet refuses to merge the migration (exit 3) and tells you to upgrade.
Its own edits stay committed locally until it can sync again.

## `dotinfra upgrade`

It looks up the latest release on GitHub, works out how dotinfra was installed and
replaces the install with exactly that release (`vX.Y.Z` below). If you already run the
latest release it says so and does nothing.

| installed with | upgrade command |
|---|---|
| pipx (pinned to a tag or not) | `pipx install --force git+https://github.com/PiotrTopa/dotinfra@vX.Y.Z` |
| `pip install --user git+...` | `python -m pip install --user -U git+https://github.com/PiotrTopa/dotinfra@vX.Y.Z` |
| pip inside a virtualenv | `python -m pip install -U git+...@vX.Y.Z` |
| a source checkout or `pip install -e` | refused: `git pull` in the checkout instead |
| system-wide | refused: use the tool that installed it, or switch to pipx |

Offline (GitHub unreachable) it falls back to `pipx upgrade dotinfra` / the bare git URL.
Plain `pipx upgrade dotinfra` keeps a tag pin such as `@v0.2.1`, so prefer `dotinfra upgrade`.

`--pre` also allows pre-releases. When run inside a CMDB (the current folder,
`--root` or `~/.infra`), it then runs `dotinfra migrate --yes` with the new
version.

`dotinfra upgrade --check` only compares the installed version with the latest
GitHub release. It has a 5 s timeout and is not an error when offline.
`dotinfra doctor --check-updates` adds the same check to the doctor report.
Without that flag, doctor stays offline.

## Managed blocks

The files dotinfra writes into a CMDB (`README.md`, `AGENTS.md`, `CLAUDE.md`,
`.gitignore`, `.gitattributes`) keep dotinfra's content between markers:

```markdown
Anything you write up here is yours.

<!-- dotinfra:managed:start v=0.2.0 -->
# home infrastructure
... rewritten by `dotinfra migrate` ...
<!-- dotinfra:managed:end -->

## Our conventions        <- yours too, never touched
```

In `.gitignore` and `.gitattributes` the markers are `# dotinfra:managed:start v=…`
and `# dotinfra:managed:end`. `v=` is the dotinfra version that last changed the
block. A refresh that changes nothing leaves the marker alone, so a new release
does not rewrite every CMDB. Edits made *inside* the markers are overwritten
at the next migrate, so add your own text above or below them instead.

Files from dotinfra 0.1.x have no markers. `migrate` compares each one with the
0.1.x template renders it knows (in the package under `templates/legacy/`):

- **unchanged** 0.1.x file: replaced by the managed version;
- **edited** 0.1.x file: the managed block goes on top and your text is kept
  below it. For `.gitignore` and `.gitattributes`, lines the block already
  contains are dropped from below. `migrate` prints a note for each such
  file. Delete whatever is now duplicated.

## `dotinfra migrate [--dry-run] [--yes]`

1. **Schema migrations.** `[cmdb] schema` in `.dotinfra.toml` counts layout
   changes. Each step is a numbered function in `dotinfra.migrate.MIGRATIONS`
   that edits the TOML text, so your comments survive. CMDBs from 0.1.x have
   no key, which counts as schema 0.
   - 0 → 1 (0.2.0): writes `schema = 1` and `min_version = "0.2.0"`. It adds
     `[monitoring] service = "monitoring"`. The 0.1 literal defaults
     `grafana_url = "http://localhost:3000"` and
     `prometheus_url = "http://localhost:9090"` become comments, because they
     would otherwise shadow the URLs derived from the monitoring service.
     Other URLs are kept as explicit overrides.
2. **Minimum version.** `[cmdb] min_version` is raised to the running release's
   `X.Y.0`. It is never lowered.
3. **Clone URL.** If `[sync] remote_url` is empty, it is filled from
   `git remote get-url <[sync] remote>`, with any credentials removed. The
   README's "Start here" section shows it.
4. **Managed blocks** are refreshed as described above.
5. **Agent Skills**: project-scope copies inside the CMDB (`[skills] project`)
   are refreshed, and so is every user-scope directory that
   `dotinfra skills install` recorded on this device
   (`~/.config/dotinfra/skills.json`).
6. **Commit.** Everything changed in the repository is committed as
   `migrate: dotinfra X.Y.Z`. `dotinfra sync` shares it.

On a terminal, `migrate` shows the plan and asks before applying it. `--yes`
skips the question, and non-interactive runs never ask. A second run changes
nothing. It refuses to run in the middle of an unfinished merge.

`dotinfra doctor` reports pending migrations ("run `dotinfra migrate --dry-run`
to see them").

## The version guard

`[cmdb] min_version` is the oldest dotinfra allowed to write to the CMDB.

- Every command that loads the CMDB exits with **code 3** and
  `this CMDB needs dotinfra ≥ X; run dotinfra upgrade` when the installed
  version is older. The read-only `ls`, `show`, `doctor`, `skills status`
  and `upgrade` only warn.
- `dotinfra sync` also checks **incoming** commits. After fetching, it reads
  `.dotinfra.toml` from each remote branch it is about to merge
  (`git show origin/main:.dotinfra.toml`). If that needs a newer dotinfra,
  nothing is merged and sync exits 3. Local edits are still committed, and
  kept for the next sync after the upgrade.

The guard needs dotinfra ≥ 0.2.0 on the device. A 0.1.x install has no guard.
It merges a 0.2 CMDB without complaint, and that is mostly harmless: 0.1.x
ignores the new keys and treats managed blocks as ordinary text. Upgrade all
devices to 0.2 first, and from then on each one protects itself.

## Per-device settings

`.dotinfra.local.toml` (ignored by git) is deep-merged over `.dotinfra.toml`
on its own device. Put anything machine-specific there: `[cmdb] device`,
vault paths, `[monitoring] role`, `bundle_dir`, or Grafana and Prometheus
URLs reached through a VPN. The shared file stays the same on every device.
