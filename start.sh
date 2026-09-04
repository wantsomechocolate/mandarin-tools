#!/usr/bin/env bash
# Opens three Windows Terminal tabs for mandarin-tools:
#   1. Frontend  - npm run dev
#   2. Backend   - uv run uvicorn app.main:app --reload
#   3. Git       - just cd'd into the project root, your default shell, no
#                  command run - ready for git commands
#
# Usage (from Git Bash, run from anywhere - the script finds its own
# location):
#   ./start.sh              local only - reachable from this computer only
#   ./start.sh --network    also reachable from other devices on this wifi
#   ./start.sh -n           same as --network
#
# Requires Windows Terminal (wt.exe) - it ships with Windows 11 by default.

set -euo pipefail

if ! command -v wt.exe >/dev/null 2>&1; then
    echo "Windows Terminal (wt.exe) not found on PATH - install it from the Microsoft Store, or add it to PATH, then try again." >&2
    exit 1
fi

# Resolve paths relative to this script's own location (not the caller's
# cwd), and in Windows form (pwd -W) since wt.exe is a native Windows exe.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -W)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_DIR="$PROJECT_ROOT/backend"

NETWORK=false
for arg in "$@"; do
    case "$arg" in
        --network|-n) NETWORK=true ;;
        *) echo "Unknown option: $arg (expected --network/-n or nothing)" >&2; exit 1 ;;
    esac
done

if $NETWORK; then
    FRONTEND_CMD="npm run dev -- --host 0.0.0.0"
    BACKEND_CMD="c"
    echo "Starting in NETWORK mode - reachable from other devices on this wifi."
    # Best-effort LAN IP guess for convenience - ignores loopback/link-local
    # addresses; if you're on multiple networks (VPN, etc.) this may pick
    # the wrong one, in which case just check `ipconfig` yourself.
    LAN_IP="$(ipconfig 2>/dev/null | grep -i 'IPv4 Address' | sed 's/.*: //' | tr -d '\r' | grep -v '^169\.254\.' | head -1 || true)"
    if [ -n "$LAN_IP" ]; then
        echo "Once both servers are up, try from your phone/other devices:"
        echo "  Frontend: http://$LAN_IP:5173"
        echo "  Backend:  http://$LAN_IP:8000/docs"
    fi
    echo "Note: MANDARIN_TOOLS_DEBUG must be set to True for the backend to accept requests from other devices on the network (see README's CORS notes)."
else
    FRONTEND_CMD="npm run dev"
    BACKEND_CMD="uv run uvicorn app.main:app --reload"
    echo "Starting in LOCAL mode - only reachable from this computer."
fi

wt.exe \
    new-tab --title "Frontend" -d "$FRONTEND_DIR" cmd /k "$FRONTEND_CMD" \; \
    new-tab --title "Backend" -d "$BACKEND_DIR" cmd /k "$BACKEND_CMD" \; \
    new-tab --title "Git" -d "$PROJECT_ROOT"
