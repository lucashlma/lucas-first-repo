#!/usr/bin/env bash
# Install TradingView Desktop (Ubuntu .deb) and launch with CDP :9222 for Cursor MCP.
set -euo pipefail

DEB_URL="https://tvd-packages.tradingview.com/ubuntu/stable/latest/jammy/tradingview_amd64.deb"
DEB_PATH="${TMPDIR:-/tmp}/tradingview_amd64.deb"

if ! command -v tradingview >/dev/null 2>&1 && [[ ! -x /opt/TradingView/tradingview ]]; then
  echo "==> Downloading TradingView Desktop..."
  curl -fL -A "Mozilla/5.0" -o "$DEB_PATH" "$DEB_URL"
  echo "==> Installing (needs sudo)..."
  sudo dpkg -i "$DEB_PATH" || sudo apt-get install -f -y
fi

BIN="$(command -v tradingview || echo /opt/TradingView/tradingview)"
export DISPLAY="${DISPLAY:-:1}"

if curl -s --max-time 1 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
  echo "CDP already up on :9222"
  curl -s http://127.0.0.1:9222/json/version
  exit 0
fi

echo "==> Launching $BIN with --remote-debugging-port=9222 (DISPLAY=$DISPLAY)"
SESSION="tradingview-cdp"
if command -v tmux >/dev/null 2>&1; then
  TMUX_CFG=""
  [[ -f /exec-daemon/tmux.portal.conf ]] && TMUX_CFG="-f /exec-daemon/tmux.portal.conf"
  # shellcheck disable=SC2086
  tmux $TMUX_CFG has-session -t "=$SESSION" 2>/dev/null || \
    tmux $TMUX_CFG new-session -d -s "$SESSION" -c "$PWD" -- bash -l
  # shellcheck disable=SC2086
  tmux $TMUX_CFG send-keys -t "$SESSION:0.0" \
    "export DISPLAY=$DISPLAY; '$BIN' --remote-debugging-port=9222 --no-sandbox 2>&1 | tee /tmp/tv-launch.log" C-m
else
  nohup "$BIN" --remote-debugging-port=9222 --no-sandbox >/tmp/tv-launch.log 2>&1 &
fi

for i in $(seq 1 45); do
  if curl -s --max-time 1 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    echo "CDP ready after ${i}s"
    curl -s http://127.0.0.1:9222/json/version
    echo
    echo "If a Welcome dialog appears, close it (X) to use charts without login (limited)."
    echo "Then: node tools/tradingview-mcp/src/cli/index.js status"
    exit 0
  fi
  sleep 1
done

echo "CDP did not come up. See /tmp/tv-launch.log"
tail -40 /tmp/tv-launch.log || true
exit 1
