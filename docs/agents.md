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

### Where skills are installed

Every agent below reads the standard `<dir>/<skill>/SKILL.md` layout. Paths
were checked against each agent's documentation on 2026-09-26:

| target | agent | user scope (`~`) | project scope (in the CMDB) | docs |
|---|---|---|---|---|
| `claude` | Claude Code | `~/.claude/skills` | `.claude/skills` | [skills](https://code.claude.com/docs/en/skills) |
| `agents` | shared convention (always installed) | `~/.agents/skills` | `.agents/skills` | [Codex skills](https://learn.chatgpt.com/docs/build-skills) |
| `copilot` | GitHub Copilot (CLI, VS Code, cloud agent) | `~/.agents/skills`¹ | `.agents/skills`¹ | [about agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) |
| `cline` | Cline | `~/.cline/skills` | `.claude/skills`² | [skills](https://docs.cline.bot/features/skills) |
| `antigravity` (`agy`) | Google Antigravity CLI and IDE | `~/.gemini/antigravity-cli/skills`, `~/.gemini/config/skills` | `.agents/skills` | [skills](https://antigravity.google/docs/skills) |
| `codex` | OpenAI Codex CLI | `~/.agents/skills` | `.agents/skills` | [skills](https://learn.chatgpt.com/docs/build-skills) |
| `gemini` | Gemini CLI | `~/.agents/skills`¹ | `.agents/skills`¹ | [skills](https://geminicli.com/docs/cli/skills/) |

¹ Copilot also reads `~/.copilot/skills` and `.github/skills`, and Gemini CLI
also reads `~/.gemini/skills` and `.gemini/skills`. Both document the
`.agents/skills` directories as well, so dotinfra installs there. That way
each skill exists only once: some agents list duplicate skill names twice or
resolve them unpredictably.
² Cline's project directories are `.cline/skills`, `.clinerules/skills` and
`.claude/skills`. dotinfra uses the one Claude Code shares.

```sh
dotinfra skills install                         # auto: detected agents + agents
dotinfra skills install --target all            # every target above
dotinfra skills install --target claude,agy     # a list (agy = antigravity)
dotinfra skills install --scope project         # into the CMDB repo (committed, synced)
dotinfra skills install --scope both --link     # user scope as symlinks (follow upgrades)
dotinfra skills status                          # installed / current / stale, per agent
```

`auto` detects an agent by its config directory (`~/.claude`, `~/.copilot`,
`~/.cline`, `~/.gemini/antigravity-cli`, `~/.codex`, `~/.gemini`) or its
binary on `PATH` (`claude`, `copilot`, `cline`, `agy`, `codex`, `gemini`).
It always includes the shared `agents` target.

**Project scope** puts the skills inside the CMDB repository, which is
committed and synced. A fresh `git clone` on a new machine then already has
them for any agent started inside `~/.infra`. `dotinfra init` installs
both scopes for the detected agents by default. It asks first on a
terminal, and `--skills LIST`, `--skills-scope` and `--yes` control it. The
installed targets are listed in `.dotinfra.toml` (`[skills] project`).

**Updates**: user-scope installs are recorded in
`~/.config/dotinfra/skills.json`. `dotinfra migrate` (run by
`dotinfra upgrade`) refreshes those and the project-scope copies.
`dotinfra doctor` shows one row per skills directory: current, stale, partial
or missing.

## Per-agent setup

The CMDB lives in `~/.infra`, but you usually work in other repositories.
Agents need a pointer from their *global* instructions.

### Claude Code

- Skills: `dotinfra skills install --target claude` (and `.claude/skills` in the CMDB).
- Global pointer, in `~/.claude/CLAUDE.md`:
  ```markdown
  Infrastructure CMDB: ~/.infra. Before any infra work read ~/.infra/AGENTS.md
  and follow it; write changes back before finishing.
  ```
- Working inside `~/.infra` itself, `CLAUDE.md` loads the rules automatically.

### OpenAI Codex CLI

- Reads `AGENTS.md` in the working directory; add the same pointer to
  `~/.codex/AGENTS.md` for global effect.
- Skills: `dotinfra skills install --target codex` (`~/.agents/skills`).

### GitHub Copilot

- Skills: `dotinfra skills install --target copilot` (`~/.agents/skills`).
  Inside the CMDB, Copilot also picks up the project-scope `.agents/skills`.
- Rules: Copilot reads `AGENTS.md` in the repository. For other repositories,
  add the pointer to your personal or repository custom instructions.

### Cline

- Skills: `dotinfra skills install --target cline` (`~/.cline/skills`).
- Rules: add the pointer to Cline's global rules, or open `~/.infra` as a
  workspace folder.

### Google Antigravity

- Skills: `dotinfra skills install --target agy`
  (`~/.gemini/antigravity-cli/skills` and `~/.gemini/config/skills`; the
  workspace skills in the CMDB are `.agents/skills`).

### Cursor, Windsurf

- Add the pointer to your user rules (Cursor: *Settings → Rules*).
- Or open `~/.infra` as a second workspace folder so the agent can read it.

### Gemini CLI

- Skills: `dotinfra skills install --target gemini` (`~/.agents/skills`).
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
