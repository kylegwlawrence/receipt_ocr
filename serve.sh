#!/usr/bin/env bash
#
# Start (or attach to) the Receipt OCR web app in a detached tmux session, so it
# keeps running after you log out. Re-running is safe: it won't start a second
# copy if the session is already up.
#
# Usage:
#   ./serve.sh           start the server in tmux (or report it's already up)
#   ./serve.sh attach    attach to the running session (Ctrl-b d to detach)
#   ./serve.sh stop      stop the server and kill the session
#   ./serve.sh status    show whether the session is running
#
# The server itself is launched by run_server.sh (binds the Tailscale IP).
set -euo pipefail

cd "$(dirname "$0")"
SESSION="receipt_ocr"

case "${1:-start}" in
    start)
        if tmux has-session -t "$SESSION" 2>/dev/null; then
            echo "Session '$SESSION' is already running. Use './serve.sh attach' to view it."
        else
            tmux new-session -d -s "$SESSION" "./run_server.sh"
            echo "Started '$SESSION'. Attach with './serve.sh attach', stop with './serve.sh stop'."
        fi
        ;;
    attach)
        tmux attach-session -t "$SESSION"
        ;;
    stop)
        tmux kill-session -t "$SESSION" 2>/dev/null && echo "Stopped '$SESSION'." \
            || echo "No '$SESSION' session was running."
        ;;
    status)
        if tmux has-session -t "$SESSION" 2>/dev/null; then
            echo "'$SESSION' is running."
        else
            echo "'$SESSION' is not running."
        fi
        ;;
    *)
        echo "Usage: $0 {start|attach|stop|status}" >&2
        exit 1
        ;;
esac
