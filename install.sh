#!/bin/sh
# Install dotinfra: pipx if available (isolated, recommended), else pip --user.
#
#   curl -fsSL https://raw.githubusercontent.com/PiotrTopa/dotinfra/main/install.sh | sh
#
# Environment:
#   DOTINFRA_SOURCE   pip requirement to install (default: the GitHub main branch)
#   PYTHON            python interpreter to use (default: python3)
set -eu

SOURCE="${DOTINFRA_SOURCE:-git+https://github.com/PiotrTopa/dotinfra}"
PYTHON="${PYTHON:-python3}"

say() { printf '%s\n' "dotinfra-install: $*"; }
die() { printf '%s\n' "dotinfra-install: error: $*" >&2; exit 1; }

command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON not found; install Python 3.11 or newer"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python 3.11 or newer is required (found $("$PYTHON" -V 2>&1))"
command -v git >/dev/null 2>&1 || die "git not found; install git first"

if command -v pipx >/dev/null 2>&1; then
    say "installing with pipx"
    pipx install --force --python "$PYTHON" "$SOURCE"
    BIN_DIR="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")"
else
    say "pipx not found; installing with pip --user (consider: $PYTHON -m pip install --user pipx)"
    if ! "$PYTHON" -m pip install --user --upgrade "$SOURCE"; then
        die "pip install failed. On distributions with an externally managed Python (PEP 668),
install pipx from your package manager (e.g. 'sudo apt install pipx') and re-run."
    fi
    BIN_DIR="$("$PYTHON" -c 'import site, os; print(os.path.join(site.USER_BASE, "bin"))')"
fi

if command -v dotinfra >/dev/null 2>&1; then
    DOTINFRA=dotinfra
elif [ -x "$BIN_DIR/dotinfra" ]; then
    DOTINFRA="$BIN_DIR/dotinfra"
    say "note: $BIN_DIR is not on your PATH; add it, e.g.:"
    say "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.profile"
else
    die "installed, but the dotinfra command was not found in PATH or $BIN_DIR"
fi

say "installed: $("$DOTINFRA" --version 2>/dev/null || echo dotinfra)"
"$DOTINFRA" doctor || true

cat <<'EOF'

Next steps:
  dotinfra init --name home        # create ~/.infra
  dotinfra skills install          # teach your AI agents the workflow
  dotinfra new server myhost --address 10.10.0.10
Docs: https://github.com/PiotrTopa/dotinfra#readme
EOF
