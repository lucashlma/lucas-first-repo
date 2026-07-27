#!/usr/bin/env bash
# Launch TradingView Desktop with Chrome DevTools Protocol (port 9222).
# Picks the platform script from the vendored tradingview-mcp tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TV_DIR="$ROOT/tools/tradingview-mcp"
cd "$TV_DIR"

case "$(uname -s)" in
  Darwin)
    exec bash ./scripts/launch_tv_debug_mac.sh "$@"
    ;;
  Linux)
    if [[ -f ./scripts/launch_tv_debug_linux.sh ]]; then
      exec bash ./scripts/launch_tv_debug_linux.sh "$@"
    fi
    echo "Trying common Linux TradingView paths with --remote-debugging-port=9222"
    for p in \
      /opt/TradingView/tradingview \
      "$HOME/.local/share/TradingView/TradingView" \
      /snap/tradingview/current/tradingview \
      tradingview
    do
      if command -v "$p" >/dev/null 2>&1 || [[ -x "$p" ]]; then
        exec "$p" --remote-debugging-port=9222 "$@"
      fi
    done
    echo "TradingView Desktop not found. Install it, then re-run."
    echo "Or ask Claude: Use tv_launch to start TradingView in debug mode"
    exit 1
    ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    exec cmd.exe /c scripts\\launch_tv_debug.bat "$@"
    ;;
  *)
    echo "Unsupported OS: $(uname -s)"
    echo "Launch manually: TradingView --remote-debugging-port=9222"
    exit 1
    ;;
esac
