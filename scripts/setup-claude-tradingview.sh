#!/usr/bin/env bash
# Replicate the BV16Dgr61EFU workflow: Claude Code ↔ TradingView Desktop via MCP.
# Usage: bash scripts/setup-claude-tradingview.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TV_DIR="$ROOT/tools/tradingview-mcp"
MCP_SERVER="$TV_DIR/src/server.js"

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

echo "==> Writing project .mcp.json (absolute path required by Claude Code)"
cat > "$ROOT/.mcp.json" << EOF
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["$MCP_SERVER"]
    }
  }
}
EOF

echo "==> Merging into ~/.claude/.mcp.json (global Claude Code config)"
mkdir -p "$HOME/.claude"
GLOBAL="$HOME/.claude/.mcp.json"
if [[ ! -f "$GLOBAL" ]]; then
  cp "$ROOT/.mcp.json" "$GLOBAL"
else
  node << NODE
const fs = require("fs");
const globalPath = process.env.HOME + "/.claude/.mcp.json";
const server = "$MCP_SERVER";
let cfg = {};
try { cfg = JSON.parse(fs.readFileSync(globalPath, "utf8")); } catch {}
cfg.mcpServers = cfg.mcpServers || {};
cfg.mcpServers.tradingview = { command: "node", args: [server] };
fs.writeFileSync(globalPath, JSON.stringify(cfg, null, 2) + "\n");
NODE
fi

echo "==> Optional: link tv CLI (npm link)"
npm link 2>/dev/null || npm link --no-fund --no-audit 2>/dev/null || true

cat << MSG

✅ Setup done.

Next steps (on a machine with TradingView Desktop):
  1. Start TradingView with CDP:
       bash "$TV_DIR/scripts/launch_tv_debug_linux.sh"
     or Mac/Windows scripts in the same folder
     or:  TradingView --remote-debugging-port=9222

  2. Restart Claude Code so it loads MCP from:
       $ROOT/.mcp.json
       and/or $HOME/.claude/.mcp.json

  3. In Claude Code say:
       Use tv_health_check to verify TradingView is connected

  4. Or CLI:
       tv status
       # or: node "$TV_DIR/src/cli/index.js" status

Project MCP config written to: $ROOT/.mcp.json
MSG
