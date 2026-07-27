#!/usr/bin/env bash
# Replicate BV16Dgr61EFU-style workflow for Cursor × TradingView MCP.
# Usage: bash scripts/setup-cursor-tradingview.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TV_DIR="$ROOT/tools/tradingview-mcp"
MCP_SERVER="$TV_DIR/src/server.js"
CURSOR_MCP="$ROOT/.cursor/mcp.json"

echo "==> Repo root: $ROOT"

if [[ ! -f "$MCP_SERVER" ]]; then
  echo "Missing $MCP_SERVER — cloning upstream..."
  mkdir -p "$ROOT/tools"
  git clone --depth 1 https://github.com/tradesdontlie/tradingview-mcp.git "$TV_DIR"
  rm -rf "$TV_DIR/.git"
fi

echo "==> npm install in tools/tradingview-mcp"
cd "$TV_DIR"
npm install

echo "==> Writing project Cursor MCP config: .cursor/mcp.json"
mkdir -p "$ROOT/.cursor"
cat > "$CURSOR_MCP" << 'EOF'
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["${workspaceFolder}/tools/tradingview-mcp/src/server.js"]
    }
  }
}
EOF

echo "==> Optional: merge into ~/.cursor/mcp.json (global Cursor)"
mkdir -p "$HOME/.cursor"
GLOBAL="$HOME/.cursor/mcp.json"
if [[ ! -f "$GLOBAL" ]]; then
  # Global needs an absolute path (no workspaceFolder outside a project)
  cat > "$GLOBAL" << EOF
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["$MCP_SERVER"]
    }
  }
}
EOF
else
  node << NODE
const fs = require("fs");
const globalPath = process.env.HOME + "/.cursor/mcp.json";
const server = "$MCP_SERVER";
let cfg = {};
try { cfg = JSON.parse(fs.readFileSync(globalPath, "utf8")); } catch {}
cfg.mcpServers = cfg.mcpServers || {};
cfg.mcpServers.tradingview = { command: "node", args: [server] };
fs.writeFileSync(globalPath, JSON.stringify(cfg, null, 2) + "\n");
NODE
fi

echo "==> Optional: link tv CLI"
npm link 2>/dev/null || npm link --no-fund --no-audit 2>/dev/null || true

cat << MSG

✅ Cursor × TradingView MCP setup done.

Next (on a machine with TradingView Desktop + Cursor):
  1. bash "$ROOT/scripts/launch-tradingview-debug.sh"
     # or: TradingView --remote-debugging-port=9222

  2. Reload Cursor / toggle MCP:
       Settings → MCP → enable "tradingview"
     Project config: $CURSOR_MCP
     (uses \${workspaceFolder}, safe to commit)

  3. In Cursor Agent chat:
       Use tv_health_check to verify TradingView is connected

  4. CLI check:
       node "$TV_DIR/src/cli/index.js" status
MSG
