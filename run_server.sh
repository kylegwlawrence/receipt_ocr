#!/usr/bin/env bash
#
# Start the Receipt OCR web app, bound to this machine's Tailscale interface so
# other devices on the tailnet (e.g. pi6 / 100.117.77.103) can reach it.
#
# By default it binds the Tailscale IP only, so the app is NOT exposed on the
# local LAN/Wi-Fi — just over Tailscale. Override any of these before running:
#   RECEIPTS_HOST  interface to bind   (default: this machine's Tailscale IP)
#   RECEIPTS_PORT  port to serve on    (default: 8005)
#   RECEIPTS_DB_PATH  SQLite file path (default: data/receipts.db)
#
# Run directly for the foreground server, or via ./serve.sh for a tmux session.
set -euo pipefail

cd "$(dirname "$0")"

# Resolve the Tailscale IPv4 address dynamically, falling back to the known one
# for this machine if the tailscale CLI isn't available.
if [[ -z "${RECEIPTS_HOST:-}" ]]; then
    if command -v tailscale >/dev/null 2>&1; then
        RECEIPTS_HOST="$(tailscale ip -4 2>/dev/null | head -n1)"
    fi
    RECEIPTS_HOST="${RECEIPTS_HOST:-100.117.77.103}"
fi
export RECEIPTS_HOST
export RECEIPTS_PORT="${RECEIPTS_PORT:-8005}"

source .venv/bin/activate

echo "Serving Receipt OCR on http://${RECEIPTS_HOST}:${RECEIPTS_PORT}"
exec python -m app.web
