# Security model

dotinfra stores a detailed map of your infrastructure and gives AI agents the
means to act on it. This page states what is protected, how, and what is not.

## What is in git (and therefore on every device and the hub)

- Component files: hostnames, IP addresses, network layout, open ports, OS
  versions, SSH users, jump-host chains, known weaknesses; with the file
  events backend, the event log (`events/<YYYY>.md`).
- `AGENTS.md`, `INDEX.md`, `.dotinfra.toml` (no secrets in it: only vault key
  *names* and paths).
- With the age backend: `vault.age`, the **encrypted** vault.

That is reconnaissance gold for an attacker even without a single password.
**Keep the hub private** — a private GitHub/Gitea repository or a bare repo on a
server you control — and treat every device holding a clone as sensitive.

## What never is

- Secret values. They live in the vault: a 0600 JSON file outside the CMDB
  (`file` backend) or age-encrypted (`age` backend).
- `.dotinfra/state/` (sync logs, probe caches), `*.local.md`, `vault.json` —
  all in `.gitignore`.
- age identities (private keys) — outside the CMDB, in `~/.config/dotinfra/`.

`dotinfra lint` fails on secret-looking content in any tracked file: private
key blocks, age identities, `password: <value>`, a quoted or backticked value
right after a credential word (Markdown notes such as `Pass: <value>`,
`Password <value>`, `password set to <value>`, `PIN is <value>`; see
[spec §9](spec.md#9-lint-rules)), AWS access key ids, GitHub tokens, `sk-...`
keys, Slack tokens. Run it before every sync (agents do). It is a safety net,
not a guarantee: it cannot recognise every credential format.

Component files are data that other devices' tools act on. `ssh-config` and
`drift` refuse `address`/`ssh.*` values that could be read as an ssh option or
smuggle a directive into `ssh_config` (a leading `-`, whitespace, control
characters); lint reports them as `unsafe`. The merge driver runs as an
ordinary `git merge-file` fallback on anything it cannot parse and never
executes content from the files it merges.

If a secret was committed and pushed, it is in the history of every clone and
the hub. **Rotate it.** Rewriting history does not reach clones that already
fetched it.

## Threat model

| threat | mitigation | residual risk |
|---|---|---|
| hub repo leaked or made public | private repo; no secrets in git; age vault is encrypted | topology and addresses exposed |
| device with a clone stolen | full-disk encryption (your responsibility); file vault is per device | that device's plaintext file vault, its age identity |
| agent echoes a secret into a transcript or log | `vault exec` pipes to stdin; skills forbid printing; deny `vault get` in agent permissions | agent disobeys; tool output containing secrets |
| agent writes a secret into a doc | lint fails; sync runs lint on reconcile | lint misses unusual formats |
| agent acts on a stale or wrong doc | "reality wins" rule, `dotinfra drift`, the event log | agents that skip verification |
| malicious edit arrives via sync | every change is a git commit naming the device; review with `git log -p` | you do not review |
| compromised peer | peers are pulled, never pushed to; merges are ordinary commits | a compromised device can push to the hub |
| monitoring endpoints exposed | bundle README: bind to LAN/VPN, firewall exporters | Prometheus and Pushgateway have no auth |

## age vault specifics

- Encrypted to each device's public key (`age_recipients` + own identity).
- Removing a device: drop its key, `dotinfra vault rekey`, sync, **and rotate**
  the secrets — it could have kept a decrypted copy or an old `vault.age`.
- Old versions of `vault.age` remain in git history, encrypted to the
  recipients of their time.
- Back up at least one identity offline. No identity, no vault.

## Recommendations

1. Private hub, SSH keys with passphrases (or hardware keys) for git.
2. Full-disk encryption on every device holding a clone.
3. Prefer the age backend when more than one device needs secrets.
4. Configure agent permissions to allow `dotinfra vault exec` and deny
   `dotinfra vault get` and reading the vault file.
5. Keep agent SSH access to what the task needs; use per-host sudo passwords
   in the vault rather than passwordless sudo everywhere.
6. Bind monitoring ports to LAN or VPN addresses.

Report vulnerabilities in dotinfra itself as described in
[SECURITY.md](../SECURITY.md).
