# Vault

CMDB files never contain secret values. They name **keys**
(`secrets: [nas_sudo]`) and explain under `## Secrets` what each key unlocks.
The values live in the vault.

## Commands

```sh
dotinfra vault list                     # key names only
dotinfra vault set nas_sudo             # prompts twice, no echo
openssl rand -base64 24 | dotinfra vault set app_token   # non-interactive: first line of stdin
dotinfra vault get nas_sudo             # prints the value (for pasting into a UI)
dotinfra vault exec nas_sudo -- ssh nas sudo -S apt upgrade -y
dotinfra vault rm old_key
dotinfra vault import ~/old-passwords.json [--overwrite]
dotinfra vault migrate --to age [--remove-plaintext]
dotinfra vault rekey                    # age: re-encrypt after adding a device
```

Values are never accepted as command-line arguments (they would end up in
shell history and `ps`).

### `vault exec`: use a secret without seeing it

`exec KEY -- CMD...` runs `CMD` with the secret plus a newline on its stdin and
exits with its exit code. This is how agents should use secrets: the value
never appears in the conversation, the terminal or logs.

```sh
# sudo reads the password from stdin with -S; -p '' hides the prompt
dotinfra vault exec gpu1_sudo -- ssh gpu1 sudo -S -p '' systemctl restart ollama

# tools that want the secret elsewhere: read it inside a small shell
dotinfra vault exec dns_api_token -- sh -c 'IFS= read -r t; curl -sH "Authorization: Bearer $t" https://api.example.net/zones'
dotinfra vault exec grafana_password -- sh -c 'IFS= read -r p; printf "GRAFANA_ADMIN_PASSWORD=%s\n" "$p" >> .env'
```

## Backends

Configure in `.dotinfra.toml`:

```toml
[vault]
backend = "file"                          # or "age"
path = "~/.config/dotinfra/vault.json"    # file backend
age_file = "vault.age"                    # age backend, relative to the CMDB root
age_identity = "~/.config/dotinfra/age.key"
age_recipients = []                       # public keys of your other devices
```

### file (default)

A JSON object `{"key": "value"}` at `path`, created with mode 0600, **outside**
the CMDB so it is never committed. Simple and dependency-free, but per device:
copy it to another device yourself (`scp`, a password manager's secure note)
or use the age backend.

### age

The same JSON, encrypted with [age](https://age-encryption.org) into
`vault.age` **inside** the CMDB, so it syncs with everything else. Every device
has its own identity (private key) and can decrypt because the file is
encrypted to all devices' public keys.

Switch an existing vault (requires `age` and `age-keygen` on PATH):

```sh
dotinfra vault migrate --to age --remove-plaintext
dotinfra sync
```

`migrate` creates this device's identity if needed, verifies the encrypted
copy, switches `backend` in `.dotinfra.toml`, and prints the public key.

**Adding a device** to an age vault:

1. On the new device (after cloning the CMDB):
   `age-keygen -o ~/.config/dotinfra/age.key` and note the `Public key: age1...` line.
2. On a device that can already decrypt: add that public key to
   `[vault] age_recipients` in `.dotinfra.toml`, run `dotinfra vault rekey`,
   then `dotinfra sync`.
3. On the new device: `dotinfra sync`, `dotinfra vault list`.

**Removing a device**: delete its key from `age_recipients`, `dotinfra vault rekey`,
sync — and rotate the secrets it had access to, since it could have kept a copy.

Guard the identity file like an SSH private key. If you lose every identity,
the vault is gone; keep an offline backup of one identity.

## Importing a legacy vault

If you kept secrets in a flat JSON file such as `~/old-secrets.json`:

```sh
dotinfra vault import ~/old-secrets.json
dotinfra vault list          # check the keys arrived
shred -u ~/old-secrets.json # or rm, once you are sure
```

Existing keys with a different value are skipped unless you pass `--overwrite`.
Nested JSON is rejected; flatten it first (`{"nas": {"sudo": "..."}}` →
`{"nas_sudo": "..."}`).

## Conventions

- Key names: `<component-id>_<purpose>` — `nas_sudo`, `router_admin`,
  `ha_long_lived_token`, `wg_hub_private_key`.
- One key per credential; do not bundle `user:password` pairs — put the
  username in the component's `## Access` section.
- After rotating: `vault set`, History line (`- 2026-09-26 — rotated router_admin`),
  sync. With the age backend, that's all other devices need.
- `dotinfra lint` warns about keys listed in `secrets:` that the vault doesn't have.
