> **This is a fictional example CMDB** shipped with dotinfra. Every name,
> address and domain is made up (documentation ranges and `example.*`).
> Explore it with `dotinfra --root examples/homelab ls`, `show gpu1`,
> `monitoring where` or `monitoring targets --stdout`, or copy it with
> `dotinfra init --example` and edit from there. This note sits outside the
> `dotinfra:managed` markers, so `dotinfra migrate` keeps it.

<!-- dotinfra:managed:start v=0.2.2 -->
# homelab infrastructure

This repository is a [dotinfra](https://github.com/PiotrTopa/dotinfra) CMDB: a
plain-Markdown record of every server, network, domain, router, service and
device, kept current by the humans and AI agents who work on them. It is
private: it holds hostnames and topology, never secret values.

## Start here — new machine

Needs **dotinfra ≥ 0.2.0**, Python ≥ 3.11, `git` and `ssh`.

1. **Install dotinfra**

   ```sh
   pipx install git+https://github.com/PiotrTopa/dotinfra
   # without pipx: python3 -m pip install --user git+https://github.com/PiotrTopa/dotinfra
   ```

2. **Clone this repository to `~/.infra`**

   ```sh
   git clone git@git.example.com:alice/homelab-infra.git ~/.infra
   ```

3. **Check the setup**: `cd ~/.infra && dotinfra doctor` (every row should be OK).

4. **Teach your AI agents the rules**: `dotinfra skills install` (Claude Code,
   GitHub Copilot, Cline, Antigravity, Codex, Gemini CLI — detected
   automatically; `--target all` for every one).

5. **Vault access** — this CMDB uses the **file** vault backend: the secrets
   live in `~/.config/dotinfra/vault.json` on each device (mode 0600, not
   synced). Copy that file from an existing device over a trusted channel, or
   `dotinfra vault import FILE`. To share them through this repository instead:
   `dotinfra vault migrate --to age`. A device can override the vault paths in
   `.dotinfra.local.toml`; `dotinfra migrate` refreshes this step when
   `[vault]` changes.

6. **Optional: sync automatically**: `dotinfra timer install` (every 15 min).

7. **Monitoring** — Prometheus and Grafana run on **nas** only (the
   `monitoring` service, `services/monitoring.md`); every other device is a
   client. `dotinfra monitoring where` prints the URLs; on nas itself run
   `dotinfra monitoring setup-server` once.

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
<!-- dotinfra:managed:end -->
