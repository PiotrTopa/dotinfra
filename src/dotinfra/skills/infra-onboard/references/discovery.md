# Discovery reference

All commands here are read-only on this machine. None of them logs in to
other hosts. Run them, collect candidates, and show the user a table before
creating any file.

## ~/.ssh/config

```sh
awk 'tolower($1)=="host"{h=$2} tolower($1) ~ /^(hostname|user|port|proxyjump)$/ {print h, $1, $2}' ~/.ssh/config
# or, per host, the fully resolved view:
ssh -G nas | grep -Ei '^(hostname|user|port|proxyjump|identityfile) '
```

- Skip wildcard patterns (`Host *`, `Host *.example.com`) and `Match` blocks.
- `Host` alias → component id (lowercase, `[a-z0-9._-]`).
- `HostName` → `address` (and `ssh.host` if it differs from the metrics address).
- `ProxyJump X` → `ssh.jump: X` — and X must become a component too.
- Also read files pulled in by `Include` lines.

## ~/.ssh/known_hosts

```sh
cut -d' ' -f1 ~/.ssh/known_hosts | tr ',' '\n' | grep -v '^|' | sed 's/^\[\(.*\)\]:\([0-9]*\)$/\1 port \2/' | sort -u
```

Entries starting with `|1|` are hashed and cannot be read; ignore them. Known
hosts are only *candidates*: the user may have visited them once.

## LAN neighbours

```sh
ip neigh show | grep -v FAILED        # Linux: IP, device, MAC, state
arp -an                               # macOS / FreeBSD
ip -4 route show default              # the default gateway = router candidate
ip -4 -o addr show | awk '{print $2, $4}'   # this machine's subnets
```

Resolve names where possible: `getent hosts IP` (Linux), `dig -x IP +short`,
or `avahi-resolve -a IP` / `dns-sd` if mDNS is available. The first 3 bytes of a
MAC (OUI) hint at the vendor (Raspberry Pi, Synology, Ubiquiti, ...).

## Optional ping sweep (only with explicit consent)

```sh
nmap -sn 10.10.0.0/24          # host discovery only, no port scan
```

Do not port-scan (`nmap -sS`, `-sV`) unless the user asks for it for a
specific host they own.

## VPN overlays

```sh
sudo wg show                   # WireGuard peers, endpoints, allowed IPs (ask before sudo)
tailscale status               # Tailscale nodes and their 100.x addresses
```

Model the overlay as one `networks/` component with a peer table, and use the
overlay address as `address` for roaming devices (it stays constant).

## Mapping to kinds

| evidence | kind |
|---|---|
| you can SSH to it / it runs an OS you manage | `server` |
| default gateway, firewall, AP with web UI | `router` |
| subnet, VLAN, VPN overlay | `network` |
| domain the user owns (from DNS, email, certs) | `domain` |
| software on a server (web UI, database, container stack) | `service` (`runs_on:`) |
| printer, UPS, camera, smart plug, switch without shell | `device` |

## What NOT to record

- Phones, TVs, guests' devices — unless the user asks.
- MAC addresses of personal devices in public repos (the CMDB repo is private, but ask).
- Anything that looks like a credential. Keys go to the vault (see `infra-vault`).
