---
name: infra-onboard
description: Guided first-time setup of a dotinfra infrastructure CMDB. Use when the user wants to start documenting their servers/homelab/VPS/network for AI agents, says "set up dotinfra", "create my infra CMDB", "document my infrastructure", "onboard my machines", when `~/.infra` (or $DOTINFRA_ROOT) does not exist yet, or when adding many existing hosts at once. Interviews the user, discovers hosts, creates component files, and optionally sets up sync, vault and monitoring.
---

# Onboard a new dotinfra CMDB

Goal: in one session, turn "I have a few machines" into a linted, synced CMDB
that every future agent reads first. Keep the user's effort minimal: ask short
questions, discover the rest, show a summary before writing.

## 0. Preconditions

```sh
dotinfra --version || pipx install git+https://github.com/PiotrTopa/dotinfra
dotinfra doctor
```

If a CMDB already exists (`dotinfra doctor` shows its root), switch to adding
components (step 4) instead of re-initialising.

## 1. Interview (one message, all questions at once)

Ask, and accept short answers:

1. What should the CMDB be called? (e.g. `home`, `lab`, `acme-prod`)
2. Which machines/devices matter? A rough list is fine: "VPS, NAS, gaming PC, Pi, router".
3. How do you reach them? LAN only / VPN (WireGuard, Tailscale) / public SSH /
   through a jump host. Which user and SSH key?
4. Which devices will hold a copy of the CMDB? (this one only / also laptop X /
   a hub: private GitHub repo or a server with SSH)
5. Do you want monitoring (Prometheus + Grafana) now, later, or never? If so,
   which one always-on machine should run it? (Only one device runs the stack.)
6. Which AI agents do you use? (Claude Code, GitHub Copilot, Cline, Antigravity,
   Codex, Gemini CLI; default: the ones installed here)
7. May I scan the local network with `nmap -sn`? (default: no)

## 2. Initialise

```sh
dotinfra init --name NAME --yes                            # detected agents' skills
dotinfra init --name NAME --remote URL --skills claude,copilot,agy --yes
```

`--remote URL` (the private hub, if the user already has one) adds the git
remote and writes the clone URL into the CMDB's README. `--skills LIST` picks
agents (`claude`, `agents`, `copilot`, `cline`, `antigravity`/`agy`, `codex`,
`gemini`, `all`, `none`). The default is the agents detected on this machine.
Skills go into the user's home directory and into the CMDB itself (committed),
so every clone carries them. Always pass `--yes`: without a terminal, `init`
does not ask anyway.

`init` writes `AGENTS.md` (the rules), `CLAUDE.md` (`@AGENTS.md`) and a
`README.md` whose "Start here — new machine" section tells anyone with access
to the private repo how to set up another device. Claude Code, Codex, Copilot
and other agents pick up the rules whenever they work inside the CMDB. Keep
machine-specific settings (`[cmdb] device`, vault paths, monitoring role) in
`~/.infra/.dotinfra.local.toml`, which git ignores, not in `.dotinfra.toml`.

## 3. Discover (read-only, no changes to any host)

Collect candidates, then merge them with the interview answers. Details and
parsing tips: [references/discovery.md](references/discovery.md).

- `~/.ssh/config` — `Host` blocks give ids, `HostName`, `User`, `Port`, `ProxyJump`.
- `~/.ssh/known_hosts` — hosts the user has connected to (hashed entries are unreadable; skip).
- `ip neigh` (Linux) / `arp -an` (macOS, BSD) — live LAN neighbours with MACs.
- `ip -4 route`, `ip -4 addr` / `ifconfig` — this machine's networks and gateway (the router).
- `wg show` / `tailscale status` if a VPN exists (may need sudo — ask first).
- `nmap -sn 10.10.0.0/24` — **only if the user said yes in question 6**.

Never log in to a host during discovery without the user's go-ahead. Never
read files outside the user's `~/.ssh` and the CMDB.

## 4. Propose, then create components

Show a table: proposed id, kind, address, how to reach it (ssh user / jump),
source (interview/ssh-config/neigh). Let the user fix names and drop noise
(phones, TVs) in one reply. Then per component:

```sh
dotinfra new server nas --title "nas — storage" --address 10.10.0.10
```

Edit each file: `status` (`active` if it is running), `role`, `tags`
(`fleet` for compute boxes the user wants on the dashboard), `ssh:` map
(`user`, `port`, `jump: <id of jump host>`), `depends_on`, `runs_on` for
services, and a first History line (`- YYYY-MM-DD — added during onboarding`).
Model the network too: one `networks/` file per LAN/VPN, the router in `routers/`,
domains the user owns in `domains/`. Prefer fewer, accurate files over many guesses.

## 5. Probe (with consent)

```sh
dotinfra ssh-config --output ~/.ssh/config.d/dotinfra   # then add to ~/.ssh/config: Include ~/.ssh/config.d/dotinfra
dotinfra drift --update                                  # ssh to each host, record OS/kernel/CPU/RAM/IPs
```

Hosts that fail: keep them, add a `## Known issues` line (`- not reachable over SSH from <device> on YYYY-MM-DD`).
Where the probe contradicts the interview, show the difference and ask.

## 6. Secrets

Ask which credentials the user wants agents to be able to use (sudo passwords,
router admin, DNS API tokens). For each: the **user** runs
`dotinfra vault set KEY`; you add `KEY` to the component's `secrets:` and a
line under `## Secrets`. Legacy JSON password file? `dotinfra vault import FILE`.
Details: `infra-vault` skill. Never accept secret values in chat; if the user
pastes one, don't repeat it, store it via `vault set`, and suggest rotating it.

## 7. Lint, index, commit

```sh
dotinfra lint && dotinfra index && dotinfra sync --no-push
```

Fix every error. Warnings about missing `role`/`updated` are worth fixing now.

## 8. Sync to other devices (if requested)

- Hub: create a **private** repo. If `init` did not get `--remote URL`, run
  `git -C ~/.infra remote add origin URL`, then `dotinfra migrate` (it records
  the clone URL in README.md) and `dotinfra sync`. On each other device follow
  the README's "Start here — new machine": install dotinfra,
  `git clone URL ~/.infra`, `cd ~/.infra && dotinfra doctor`, `dotinfra skills install`.
- Peers without a hub: `dotinfra peer add laptop ssh://laptop/~/.infra` on each side.
- Background sync: `dotinfra timer install --interval 15m` on each device.
- Vault on other devices: see `infra-vault` (age backend syncs; file backend is copied out of band).

## 9. Monitoring (if requested)

Hand over to the `infra-monitoring` skill: record the stack as
`services/monitoring.md` with `runs_on: <the chosen host>`, add
`metrics: [node:9100]` to hosts that run node_exporter, then **on that host**
run `dotinfra monitoring setup-server`, start the stack and
`dotinfra timer install`. Other devices stay clients; `dotinfra monitoring where`
shows them where Grafana is.

## 10. Wrap up

Summarise for the user: number of components by kind, what was probed, what
is unverified (Known issues), where the CMDB lives, how sync is set up, and
the one habit that matters: *agents read the CMDB first and write back after
every change* — it is in `AGENTS.md` and the installed skills.
