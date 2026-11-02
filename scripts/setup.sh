#!/usr/bin/env bash
# Bootstraps a local dev environment: .env, and dependencies for every
# toolchain in the repo. Safe to re-run. See README.md for what to run
# after this (docker compose, or each service standalone).
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

echo "==> .env"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "created .env from .env.example"
else
    echo ".env already exists, leaving it alone"
fi

echo "==> kernel (Go)"
if command -v go >/dev/null 2>&1; then
    (cd kernel && go mod download)
else
    echo "go not found on PATH, skipping (install Go: https://go.dev/dl/)" >&2
fi

echo "==> apps (Python)"
if command -v pip >/dev/null 2>&1; then
    for app in crm invoicing projects inventory; do
        echo "  -- apps/$app"
        pip install -q -r "apps/$app/requirements.txt" -r "apps/$app/requirements-dev.txt"
    done
else
    echo "pip not found on PATH, skipping" >&2
fi

echo "==> pos-engine (Rust)"
if command -v cargo >/dev/null 2>&1; then
    (cd pos-engine && cargo build)
    if ! command -v wasm-pack >/dev/null 2>&1; then
        echo "  wasm-pack not found, installing (this can take a minute the first time)"
        cargo install wasm-pack
    fi
    (cd pos-engine && wasm-pack build --target web --out-dir ../web/src/apps/pos/engine --out-name friday_pos_engine)
else
    echo "cargo not found on PATH, skipping (install Rust: https://rustup.rs)" >&2
fi

echo "==> web (Node)"
if command -v npm >/dev/null 2>&1; then
    (cd web && npm install)
else
    echo "npm not found on PATH, skipping (install Node: https://nodejs.org)" >&2
fi

cat <<'EOF'

Setup done. Next:
  docker compose -f infra/docker-compose.yml up
or run each service standalone -- see README.md's "Per-language dev commands".
EOF
