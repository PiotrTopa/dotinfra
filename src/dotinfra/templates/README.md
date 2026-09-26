# {{name}} infrastructure

This repository is a [dotinfra](https://github.com/PiotrTopa/dotinfra) CMDB: a
plain-Markdown record of every server, network, domain, router, service and
device, kept current by the humans and AI agents who work on them. It is
private: it holds hostnames and topology, never secret values.

## Start here — new machine

Needs **dotinfra ≥ {{min_version}}**, Python ≥ 3.11, `git` and `ssh`{{age_note}}.

1. **Install dotinfra**

   ```sh
   pipx install git+https://github.com/PiotrTopa/dotinfra
   # without pipx: python3 -m pip install --user git+https://github.com/PiotrTopa/dotinfra
   ```

2. **Clone this repository to `~/.infra`**

   ```sh
   git clone {{clone_url}} ~/.infra
   ```
{{clone_note}}
3. **Check the setup**: `cd ~/.infra && dotinfra doctor` (every row should be OK).

4. **Teach your AI agents the rules**: `dotinfra skills install` (Claude Code,
   GitHub Copilot, Cline, Antigravity, Codex, Gemini CLI — detected
   automatically; `--target all` for every one).{{project_skills}}

5. **Vault access** — this CMDB uses the **{{vault_backend}}** vault backend.
   - `file`: secrets live outside the repository (`~/.config/dotinfra/vault.json`).
     Copy that file from an existing device over a trusted channel, or
     `dotinfra vault import FILE`.
   - `age`: the encrypted `vault.age` is in this repository. Run
     `dotinfra vault identity` and `dotinfra sync` here, then on a device that
     can already decrypt: `dotinfra sync && dotinfra vault rekey && dotinfra sync`;
     finally `dotinfra sync` here again.

6. **Optional: sync automatically**: `dotinfra timer install` (every 15 min).

{{monitoring}}

Anything specific to one machine (its device name, vault paths, the monitoring
role, Grafana/Prometheus URLs reached over a VPN) goes in
`~/.infra/.dotinfra.local.toml`. That file is ignored by git and overrides
`.dotinfra.toml` on this machine only.

## Keeping dotinfra up to date

`dotinfra upgrade` installs the latest dotinfra and then runs `dotinfra migrate`,
which refreshes the parts of this repository that dotinfra owns (the blocks
between `dotinfra:managed` markers in README.md, AGENTS.md, CLAUDE.md,
.gitignore and .gitattributes, plus the Agent Skills) and records the minimum
version in `.dotinfra.toml`. Text outside the markers is yours and is never
changed. A device whose dotinfra is older than that minimum refuses to sync
until it is upgraded.

## Layout

| folder | what goes there |
|---|---|
| `servers/` | machines you can log into (VMs, SBCs, NAS, workstations) |
| `networks/` | LANs, VLANs, VPN overlays |
| `domains/` | domain names and their DNS |
| `routers/` | gateways, firewalls, access points with a management UI |
| `services/` | software running somewhere (`runs_on:` a server) |
| `devices/` | everything else with a network address or a warranty |

`INDEX.md` is the generated inventory. `AGENTS.md` holds the rules agents
follow (Claude Code reads it through `CLAUDE.md`).

## The rules, in short

1. **Read first.** Look up a component before touching it.
2. **Write back.** Update its file in the same sitting: facts in the
   frontmatter, prose in the sections, a dated line in `## History`.
3. **No secrets here.** Only vault key names; values live in `dotinfra vault`.
4. **Check and sync.** `dotinfra lint`, then `dotinfra sync`.

## Everyday commands

```sh
dotinfra new server nas --address 10.10.0.10    # new component from a template
dotinfra ls --kind server                        # inventory
dotinfra show nas                                # one component
dotinfra lint                                    # schema, references, leaked secrets
dotinfra ssh-config --output ~/.ssh/config.d/dotinfra
dotinfra vault set nas_sudo                      # store a secret (prompted)
dotinfra sync                                    # commit + exchange with other devices
dotinfra drift nas                               # compare the doc with the live host
dotinfra monitoring where                        # where Grafana/Prometheus run
```
