# homelab infrastructure

> **This is a fictional example CMDB** shipped with dotinfra. Every name,
> address and domain is made up (documentation ranges and `example.*`).
> Explore it with `dotinfra --root examples/homelab ls`, `show gpu1`,
> `ssh-config` or `monitoring targets --stdout`, or copy it with
> `dotinfra init --example` and edit from there.

This folder is a [dotinfra](https://github.com/PiotrTopa/dotinfra) CMDB: a
plain-Markdown record of every server, network, domain, router, service and
device, kept current by the humans and AI agents who work on them.

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
dotinfra new server nas --address 10.10.0.10   # new component from a template
dotinfra ls --kind server                        # inventory
dotinfra show nas                                # one component
dotinfra lint                                    # schema, references, leaked secrets
dotinfra ssh-config --output ~/.ssh/config.d/dotinfra
dotinfra vault set nas_sudo                      # store a secret (prompted)
dotinfra sync                                    # commit + exchange with other devices
dotinfra drift nas                               # compare the doc with the live host
```
