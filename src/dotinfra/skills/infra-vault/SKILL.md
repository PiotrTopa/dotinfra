---
name: infra-vault
description: Handle infrastructure secrets with the dotinfra vault. Use whenever a task needs a password, sudo password, API token, private key, WireGuard key, database or admin credential for a host or service in the CMDB; when storing or rotating a credential; when `dotinfra lint` reports secret-looking content; or when importing a legacy JSON password file. Never ask the user to paste secrets into chat and never write secret values into files.
---

# Infra vault: key names in docs, values in the vault

Components list the keys they need in `secrets: [...]` and describe them under
`## Secrets`. Values live only in the vault (`dotinfra vault`), which is either a
0600 JSON file outside the CMDB (`file` backend) or an `age`-encrypted
`vault.age` inside it (`age` backend, syncs with the CMDB).

## Using a secret (preferred: never see it)

Pipe it to the consumer's stdin; nothing lands in argv, history or your output:

```sh
dotinfra vault exec nas_sudo -- ssh nas sudo -S systemctl restart nfs-server
dotinfra vault exec grafana_password -- sh -c 'IFS= read -r p; curl -su "admin:$p" http://10.10.0.10:3000/api/health'
dotinfra vault exec db_admin -- psql "host=db user=admin" --no-password   # only if the tool reads stdin
```

- `sudo -S` reads the password from stdin. Add `-p ''` to hide the prompt.
- Anything that only accepts a secret as an argument or env var: wrap it in
  `sh -c 'IFS= read -r s; TOOL --token "$s"'` so it never appears in your transcript.
- `dotinfra vault get KEY` prints the value. Use it only when a value must be
  pasted into a UI by the user — and then let the user run it, not you.
- Never print, echo, log or summarise a secret value. If one appears in output
  by accident, tell the user so they can rotate it.

## Storing and rotating

```sh
dotinfra vault list                 # key names only
dotinfra vault set KEY              # prompts (getpass); never pass values as args
dotinfra vault rm KEY
```

`set` is interactive: ask the user to run it themselves, e.g.
"Please run `dotinfra vault set router_admin` and paste the new password at the prompt."
Generating a new random credential is fine without user input:
`openssl rand -base64 24 | dotinfra vault set KEY` (non-interactive `set` reads
the first line of stdin). Then apply it with `vault exec`, never by pasting it.

After storing or rotating: add the key to the component's `secrets:`, describe
it under `## Secrets` (what it unlocks, not the value), add a History line
(`- 2026-09-26 — rotated router_admin`), `dotinfra lint`, `dotinfra sync`.

Key naming: `<component-id>_<purpose>` — `nas_sudo`, `router_admin`,
`ha_long_lived_token`, `wg_hub_private_key`.

## Lint found a secret

`dotinfra lint` flags private key blocks, age identities, `password: <value>`,
AWS/GitHub/OpenAI-style tokens and Slack tokens in tracked files. It also flags
a quoted or backticked value right after a credential word, the way notes are
usually written in Markdown: `Pass: <value>`, `Password <value>`, `password set
to <value>`, `PIN is <value>` with the value in backticks or quotes (words:
pass, passwd, password, pwd, passphrase, pin, token, secret, api key; pin,
pass, token, secret and api key only with `:`, `=`, `is` or `set to`). Not
flagged: `passwordless sudo`, `password auth disabled`, `PasswordAuthentication
no`, lines that mention the vault (`Password in vault (<key>)`, `dotinfra
vault exec <key> -- ...`), placeholders (`<password>`, `***`, `{{ var }}`),
paths (values starting with `~`, `/`, `./` or `$`) and ALL_CAPS variable names.
Write a vault reference instead of the value, e.g. "alice: sudo password in
the vault, key `host_sudo`".

1. Move the value into the vault (`dotinfra vault set KEY`, user runs it).
2. Replace it in the file with the key name.
3. If the file was already committed and synced, the value is in git history on
   every device and the hub: tell the user to **rotate** the credential. Rewriting
   history is not enough once it has been pushed.
4. False positive (e.g. a documented example)? Only with the user's agreement,
   append `dotinfra:allow-secret` to that line.

## Backends

- **file** (default): `~/.config/dotinfra/vault.json`, mode 0600, per device, not synced.
  Copy it to new devices out of band (`scp`), or switch to age.
- **age**: `dotinfra vault migrate --to age` encrypts into `vault.age` in the CMDB.
  Each device has its own identity (`~/.config/dotinfra/age.key`); `[vault]
  age_recipients` lists every device's public key and syncs with the CMDB.
  Adding a device: `dotinfra vault identity && dotinfra sync` on it, then
  `dotinfra sync && dotinfra vault rekey && dotinfra sync` on a device that can
  already decrypt, then `dotinfra sync` on the new one. "identity not found"
  means exactly this is still to do.
- Legacy flat JSON `{"key": "value"}` file: `dotinfra vault import FILE`, verify
  with `dotinfra vault list`, then ask the user to delete the old file.
