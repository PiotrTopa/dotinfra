---
name: infra-sync
description: Synchronise the dotinfra infrastructure CMDB between devices and resolve merge conflicts. Use after editing CMDB files, when `dotinfra sync` exits with code 2 or prints CONFLICT, when `.dotinfra/state/RECONCILE.md` exists, when `dotinfra status` shows the CMDB ahead/behind/diverged, when adding a new device, hub or peer, or when the user mentions copies of ~/.infra being out of sync.
---

# Infra sync and conflict reconciliation

The CMDB is a git repo (branch `main`). Devices exchange commits through a
**hub** remote (private GitHub/Gitea repo or bare repo over SSH) and/or directly
with **peers** (`ssh://host/~/.infra`). `dotinfra sync` commits local edits,
fetches, merges (never rebases), pushes to the hub, and regenerates `INDEX.md`.
A section-aware merge driver resolves most `.md` conflicts on its own.

## Everyday

```sh
dotinfra status          # dirty files, ahead/behind per remote, conflicts
dotinfra sync            # safe to run any time; idempotent
dotinfra sync --dry-run  # show what would happen
```

Exit codes: `0` done, `2` conflicts need you, anything else = error (read it).
Never "fix" sync problems with `rsync`, `cp`, `git reset --hard`, `git push --force`
or by deleting and re-cloning — each silently discards another device's edits.

## When sync exits 2: reconcile

1. Read `.dotinfra/state/RECONCILE.md`. It lists every conflicted file and each
   conflict block (the H2 section or frontmatter key, with both versions).
2. Open each listed file. Conflicts are confined to single sections, marked:
   ```
   <<<<<<< ours
   (this device's version)
   =======
   (the other device's version)
   >>>>>>> theirs
   ```
3. Resolve **section by section**. For each block decide which version matches
   *reality*, not which is newer:
   - Both describe different true facts (two package installs, two new ports)
     → keep both, merged into one coherent section.
   - They contradict (different IP, different OS version, different status)
     → **probe when unsure**: `dotinfra drift ID` (or `ssh ID` + the relevant
     command: `ip -4 addr`, `cat /etc/os-release`, `systemctl is-active X`,
     `dig +short NAME`). Keep what the host actually shows.
   - Cannot verify (host offline, no access) → keep the version with the most
     recent evidence, and add a line under `## Known issues`:
     `- unverified: address 10.10.0.21 vs 10.10.0.22 after merge on 2026-09-26`.
   - Frontmatter scalar conflicts (`status`, `address`, `os`, `role`) follow the
     same rule. Lists are already unioned by the driver; drop entries that are
     no longer true.
   - `## History` is merged automatically (union, newest first). If markers
     remain there, keep every dated line from both sides; never drop history.
4. Remove all markers. Keep frontmatter valid (the YAML subset; see `infra-cmdb`).
   Set `updated:` to today on files where you changed facts.
5. Finish:
   ```sh
   dotinfra reconcile --continue   # verifies no markers, lints, commits the merge, pushes
   ```
   If lint fails, fix and rerun. To give up and restore the pre-merge state:
   `dotinfra reconcile --abort` (the other side's changes stay fetched for later).
6. Tell the user which conflicts you resolved and how, especially any you
   decided by probing or could not verify.

Non-Markdown conflicts (`.dotinfra.toml`, `vault.age`): do not guess.
For `vault.age` take the side with more keys, then ask the user to re-set any
secret changed on the other device and run `dotinfra vault rekey`.

## Topology and setup

- Hub (recommended for 3+ devices): `git remote add origin git@github.com:alice/infra.git`
  on the first device, `dotinfra sync`; on the others `git clone <hub> ~/.infra`.
  The hub repo must be **private**.
- Peers (no hub, two or three always-on machines): `dotinfra peer add NAME ssh://HOST/~/.infra`,
  `dotinfra peer ls`, `dotinfra peer rm NAME`. Sync pulls from peers but never
  pushes into them; each peer pulls for itself.
- Automatic: `dotinfra timer install --interval 15m` (systemd user timer; prints
  a cron line where systemd is unavailable). `dotinfra timer remove` undoes it.
- New device checklist: clone, `dotinfra doctor`, copy or re-key the vault
  (`infra-vault` skill), then `dotinfra sync` (it registers the merge driver in
  the clone's git config; plain `git pull` would not use it).

## Migrating copies that were kept in sync with rsync/scp

- Copies **share git history** (one was cloned from the other): commit on each
  (`dotinfra sync --no-push`), then sync them through the hub or as peers; the
  merge driver reconciles the divergence. Review the resulting RECONCILE.md.
- Copies **do not share history** (independent `git init`s, or plain folders):
  pick the most complete copy as canonical and push it to the hub. On each other
  device, move the old copy aside (`mv ~/.infra ~/.infra.old`), clone the hub,
  then compare (`diff -ru ~/.infra.old ~/.infra`) and re-apply real differences
  by editing files — section by section, same rules as above. Then sync.
  Never merge unrelated histories blindly with `--allow-unrelated-histories`.
