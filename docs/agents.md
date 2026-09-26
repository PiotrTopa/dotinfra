# Working with AI agents

dotinfra gives agents two things: **rules** (always loaded) and **skills**
(loaded when relevant).

## Rules: `AGENTS.md`

`dotinfra init` writes `AGENTS.md` into the CMDB root. It tells any agent to:

1. read `INDEX.md` and the relevant component files before infra work;
2. write reality back in the same turn — facts, prose, a dated History line, `updated:`;
3. keep secrets in the vault and reference keys only;
4. `dotinfra lint`, then `dotinfra sync` (and reconcile on exit code 2);
5. treat the host as the truth when it contradicts the doc.

`CLAUDE.md` contains `@AGENTS.md`, which Claude Code expands. Edit `AGENTS.md`
to add house rules ("never reboot the NAS during the day"); it syncs like
everything else.

## Skills

Bundled [Agent Skills](../src/dotinfra/skills/) (a `SKILL.md` with a `name` and a
trigger-rich `description`, loaded on demand):

| skill | loaded when the agent... |
|---|---|
| `infra-cmdb` | is about to touch hosts, networks, DNS, services — or just changed something |
| `infra-vault` | needs a credential, stores or rotates one, or lint found a secret |
| `infra-sync` | syncs, hits a conflict (exit 2, `RECONCILE.md`), adds a device |
| `infra-onboard` | is asked to set up a CMDB from scratch or add many hosts |
| `infra-monitoring` | adds a host to monitoring, deploys the stack, records an event |

```sh
dotinfra skills install                 # default target(s)
dotinfra skills install --target claude # ~/.claude/skills
dotinfra skills install --target agents # ~/.agents/skills
dotinfra skills install --link          # symlink instead of copy (follows upgrades)
```

## Per-agent setup

The CMDB lives in `~/.infra`, but you usually work in other repositories.
Agents need a pointer from their *global* instructions.

### Claude Code

- Skills: `dotinfra skills install --target claude`.
- Global pointer, in `~/.claude/CLAUDE.md`:
  ```markdown
  Infrastructure CMDB: ~/.infra. Before any infra work read ~/.infra/AGENTS.md
  and follow it; write changes back before finishing.
  ```
- Working inside `~/.infra` itself, `CLAUDE.md` loads the rules automatically.

### OpenAI Codex CLI

- Reads `AGENTS.md` in the working directory; add the same pointer to
  `~/.codex/AGENTS.md` for global effect.
- Skills: `dotinfra skills install --target agents`.

### Cursor, Windsurf, Cline

- Add the pointer to your user rules (Cursor: *Settings → Rules*; Cline:
  `.clinerules` or global custom instructions).
- Or open `~/.infra` as a second workspace folder so the agent can read it.

### Gemini CLI

- In `~/.gemini/settings.json`, include `AGENTS.md` in `contextFileName`
  (`["GEMINI.md", "AGENTS.md"]`), and put the pointer in `~/.gemini/GEMINI.md`.

### Other agents

Anything that accepts a system prompt: *"Before any infrastructure work, read
~/.infra/AGENTS.md and follow it."* Agents that support the Agent Skills
format can load `~/.agents/skills`.

## Letting agents act safely

- Give agents SSH access through the same config you use (`dotinfra ssh-config`
  writes aliases with jump hosts, so `ssh nas` just works).
- Secrets: agents use `dotinfra vault exec KEY -- CMD`. They never need to see a
  value. Your agent's permission settings can allow `dotinfra vault exec` and
  deny `dotinfra vault get`.
- Review agent edits in git: `git -C ~/.infra log -p -3`. Every sync commit names
  the device and files.
- Onboarding with an agent: *"Use the infra-onboard skill to set up my CMDB."*

## What good write-back looks like

```diff
 ---
 status: active
-os: Ubuntu 22.04 LTS
+os: Ubuntu 24.04 LTS
-updated: 2026-05-30
+updated: 2026-09-26
 ---
 ## Configuration
-- NVIDIA driver 560
+- NVIDIA driver 570 (graphics PPA); DCGM exporter image bumped to match
 ## History
+- 2026-09-26 — release upgrade to 24.04; driver 570; exporters verified
 - 2026-05-30 — added dcgm:9400 to metrics
```

Facts in frontmatter, specifics in prose, one dated History line, nothing secret.
