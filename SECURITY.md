# Security policy

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private vulnerability
reporting ("Report a vulnerability" on the repository's *Security* tab).
Include steps to reproduce and the affected version (`dotinfra --version`).

You will get an acknowledgement within a week. Fixes are released as a patch
version and credited in the changelog unless you prefer otherwise.

## Scope

In scope: anything that can make dotinfra leak a secret (into git, logs, error
messages, process arguments, generated files), weaken file permissions of the
vault, execute unintended commands (e.g. via crafted component files, merge
driver input or remote names), or corrupt the CMDB during sync.

Out of scope: the security of your hub repository, devices and monitoring
endpoints; see [docs/security.md](docs/security.md) for the threat model and
recommendations.

## Supported versions

The latest release receives fixes.
