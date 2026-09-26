# Migrating existing notes

Already keeping infrastructure notes in a folder — Markdown, an Obsidian vault
section, text files? This turns them into a dotinfra CMDB without losing
anything. Work on a copy until you are happy.

## 1. Initialise in place (or next to it)

```sh
cp -a ~/notes/infra ~/infra-before-dotinfra      # safety copy
dotinfra init ~/.infra --name home               # fresh CMDB with rules and folders
```

Upgrading a CMDB created by an older dotinfra is a different task: see
[upgrading](upgrading.md) (`dotinfra upgrade`, `dotinfra migrate`).

If your notes already live in `~/.infra` and are a git repository, run
`dotinfra init ~/.infra` there: existing files are left alone, and missing
scaffolding (`.dotinfra.toml`, `AGENTS.md`, `.gitattributes`, folders) is added.
If `init` refuses a non-empty folder in your version, initialise elsewhere and
move the files in.

## 2. One file per component, in the right folder

| you have | becomes |
|---|---|
| `nas.md`, `server-notes/gpu-box.txt` | `servers/nas.md`, `servers/gpu1.md` |
| `network.md` describing LAN + VPN | `networks/lan.md`, `networks/wireguard.md` |
| `dns.md` with three domains | `domains/example.com.md`, ... one per domain |
| a "services" list | one file per service in `services/`, each with `runs_on:` |
| `passwords.txt` | **the vault** (step 5), never a Markdown file |

Rename to lowercase ids (`[a-z0-9._-]`), convert `.txt` to `.md`. Use `git mv`
if the folder is already a repo so history follows the files.

## 3. Add frontmatter

The minimum is `status`:

```markdown
---
status: active
role: ZFS storage and backups
address: 10.10.0.10
updated: 2026-09-26
---

# nas
...your existing notes, unchanged...
```

Then, as you go, move facts that tools can use into frontmatter: `ssh`
(user/port/jump), `metrics`, `secrets`, `depends_on`, `runs_on`, `tags`. See the
[schema](schema.md). Leave prose where it is.

Optional but valuable: regroup prose under the standard H2 sections
(`Overview`, `Access`, `Configuration`, `Constraints & known issues`).
Sync merges per section, so this pays off as soon as two devices edit.
Docs state what *is*: fold any changelog you kept into current facts, and move
events worth remembering to the event log (`dotinfra event add --time
2025-11-02 ...`, see [events](events.md)) instead of keeping a History section.

An agent does this well: *"Use the infra-cmdb skill. Convert every file in
~/.infra to the dotinfra schema: add frontmatter, move facts into it, keep all
current facts as a concise fact sheet, move history to `dotinfra event add`,
don't invent facts, mark anything uncertain under Constraints & known issues."*

## 4. Lint until clean

```sh
dotinfra lint
```

Typical first-run findings and fixes:

| message | fix |
|---|---|
| parse error at `file:line` | unsupported YAML (multi-line string, nested map) — simplify |
| missing `status` | add `status: active` (or `planned`/`retired`) |
| `kind` does not match folder | move the file or fix `kind:` |
| unknown id in `depends_on` / `ssh.jump` | create that component or fix the id |
| secret-looking content | move the value to the vault (step 5) and write the key name |
| stale `updated` (warning) | verify the facts, then set today's date |

Then `dotinfra index` and `dotinfra drift --update` to check the notes against
the live hosts.

## 5. Import a legacy vault

If you kept secrets in a flat JSON file (for example `~/old-secrets.json` with
`{"nas_sudo": "...", "router_admin": "..."}`):

```sh
dotinfra vault import ~/old-secrets.json
dotinfra vault list
```

Then list those keys in each component's `secrets:` and delete the old file.
Secrets that were in Markdown: `dotinfra vault set KEY` for each, replace the
value with the key name, and **rotate** any that were ever committed or synced
anywhere.

If you had a home-grown wrapper script for secrets, replace its uses with
`dotinfra vault get KEY` / `dotinfra vault exec KEY -- CMD`, or keep it as a tiny
shim that calls dotinfra.

## 6. Commit and sync

```sh
dotinfra sync --no-push                   # first commit
git -C ~/.infra remote add origin <private repo>
dotinfra sync
```

Other devices: see [sync — migrating from rsync-mirrored copies](sync.md#migrating-from-rsync--or-scp-mirrored-copies).

## 7. Tell your agents

`dotinfra skills install` (it detects Claude Code, Copilot, Cline, Antigravity,
Codex and Gemini CLI; `--scope project` also commits the skills into the CMDB),
and add the global pointer described in
[agents](agents.md). From now on, agents keep the CMDB current as part of
every infra task.
