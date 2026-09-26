# Contributing

Thanks for helping. dotinfra is small on purpose; contributions that keep it
small, dependency-free and predictable are the easiest to merge.

## Ground rules

- **Read [docs/spec.md](docs/spec.md) first.** It is the contract. A change that
  alters behaviour updates the spec in the same pull request.
- **Standard library only** at runtime (Python ≥ 3.11). External tools (`git`,
  `ssh`, `age`) are called as subprocesses and must be optional where possible.
- **No personal data** in code, tests, docs or examples. Use `example.com` /
  `.net` / `.org`, documentation IP ranges (`192.0.2.0/24`, `198.51.100.0/24`,
  `203.0.113.0/24`, `2001:db8::/32`), `10.10.0.0/16` for LANs, and the user `alice`.
- Generated output must be deterministic (same CMDB → byte-identical files).
- Nothing secret is ever written into the CMDB, logs or error messages.

## Development

```sh
git clone https://github.com/PiotrTopa/dotinfra && cd dotinfra
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/dotinfra --root examples/homelab lint
.venv/bin/dotinfra --root examples/homelab index --check
```

Tests use `unittest` only and must not touch `~`, the network or real hosts:
use temporary directories, set `DOTINFRA_ROOT`/`HOME` for subprocesses, and
mock `urllib.request.urlopen` for HTTP.

## Pull requests

- One topic per PR, with tests for new behaviour and a line in `CHANGELOG.md`
  under *Unreleased*.
- Keep CLI output friendly and stable; scripts may parse `--json` output, so
  treat JSON shapes as API.
- Skills (`skills/*/SKILL.md`) stay under ~200 lines; longer material goes in
  the skill's `references/`.
- English only in code, docs and commit messages.

## Reporting bugs

Use the issue templates. Include `dotinfra doctor` output and, if relevant, a
minimal *fictional* component file that reproduces the problem. Never paste
real secrets, hostnames or addresses you don't want public.
