# Infrastructure CMDB — rules for AI agents

This folder is the source of truth for the infrastructure of **{{name}}**: one
Markdown file per server, network, domain, router, service and device. Humans
and agents share it. These rules are mandatory for any task that touches
infrastructure (hosts, networks, DNS, services, credentials, monitoring).

## 1. Read before you act

- Before any infra work, read `INDEX.md`, then the file of every component you
  will touch **and** the components it `depends_on` or `runs_on`.
- Run `dotinfra ls` / `dotinfra show ID` when you need facts fast.
- `events/` (the event log, if this CMDB keeps one) is history, not state: do
  not load it by default; query it (`dotinfra event list --host ID`) only when
  the task is about what happened and when.
- Trust the doc, but verify: if what you observe on a host contradicts the file,
  reality wins — see *Drift* below.

## 2. Write reality back in the same turn

Component files are **fact sheets of what is true now**, not journals. Agents
read them on every task, so every line costs context: keep them short, current
and cheap to read. After every change you make or discover — installed a
package, opened a port, rotated a credential, found a host was renamed —
update the CMDB **before you finish the task**, not "later":

- Edit the right component file (`servers/ID.md`, `services/ID.md`, ...). One
  component per file; create new ones with `dotinfra new KIND ID`.
- Keep frontmatter facts true (`status`, `address`, `os`, `ssh`, `metrics`,
  `secrets`, `depends_on`, `runs_on`) and set `updated:` to today (`YYYY-MM-DD`).
- **Edit facts in place.** Rewrite the line that is no longer true; never
  append "on <date> we did X". Delete issues once they are resolved.
- **Events go to the event log, not the doc**: `dotinfra event add --host ID
  --type change|maintenance|outage|incident|observation "what happened"`.
  Old versions of every doc stay in git history.
- Sections: `Overview` (2–3 lines), `Access`, `Configuration` (or `Hardware`,
  `Services`), `Constraints & known issues`. Aim for ≤ 40 lines for a simple
  component, ≤ 80 for a complex one; `dotinfra lint` warns about history
  sections (`journal`) and overlong docs (`long`).
- Do not rename or reorder existing headings — sync merges files section by
  section.
- Write in English, concisely, as facts a stranger could act on.

## 3. Secrets never go in these files

- Store every credential in the vault and write only its **key name** here:
  `dotinfra vault set KEY` (prompts, never on the command line).
- Use a secret without printing it: `dotinfra vault exec KEY -- sudo -S CMD`
  (the secret goes to the command's stdin). Use `dotinfra vault get KEY` only
  when a value must be pasted somewhere, and never echo it into chat or logs.
- List the keys a component needs in its `secrets:` frontmatter.
- Never paste private keys, tokens, or credentials into Markdown, commit
  messages or shell history. `dotinfra lint` fails when it finds one.

## 4. Check, commit, sync

1. `dotinfra lint` — fix every error (warnings are advice).
2. `dotinfra index` — refresh `INDEX.md` if you added/renamed components.
3. `dotinfra sync` — commits, exchanges changes with the other devices and pushes.
   If it exits with code 2 there is a conflict: read
   `.dotinfra/state/RECONCILE.md`, fix the marked sections so both sides' facts
   survive, then run `dotinfra reconcile --continue`. Never discard the other
   side's edits and never `rsync --delete` between copies.

## 5. Drift

- `dotinfra drift ID` probes a host over SSH and compares it with its file.
- When the host is right and the doc is wrong: correct the doc (or run
  `dotinfra drift ID --update`); record notable drift with
  `dotinfra event add --type observation`.
- When the doc describes intended state and the host is wrong: say so to the
  user before changing the host, and record the outcome.
- If you cannot verify something, write it down under
  `## Constraints & known issues` rather than guessing.

## 6. Scope

- Do not delete component files; set `status: retired` and record it with
  `dotinfra event add`.
- Files ending in `.local.md` are private to this device and never synced.
- `INDEX.md` is generated — edit component files, then run `dotinfra index`.

## 7. Tooling

- If a `dotinfra` command exits with code 3, this device's dotinfra is older
  than the CMDB's `[cmdb] min_version`: run `dotinfra upgrade` (it also runs
  `dotinfra migrate`), never work around the check.
- Text between `dotinfra:managed` markers (in this file, README.md, CLAUDE.md,
  .gitignore, .gitattributes) is rewritten by `dotinfra migrate`. Put local
  additions outside the markers.
- Machine-specific settings go in `.dotinfra.local.toml` (untracked), never in
  `.dotinfra.toml`, which every device shares.
- Monitoring runs on one machine: `dotinfra monitoring where` says which one and
  whether this device is it. Deploy or change the stack only there.
