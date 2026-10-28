#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v blender >/dev/null 2>&1; then
  echo "未找到 Blender。请先从 https://www.blender.org/download/ 安装 Blender 4.x 或更高版本。"
  exit 1
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "正在通过 Astral 官方安装器安装 uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "uvx 安装后仍不可用。请重开终端，确认 'which uvx' 有输出后重试。"
  exit 1
fi

echo "Blender: $(blender --version | sed -n '1p')"
echo "uvx: $(command -v uvx)"
echo "正在安装最新版 MCP for Blender 插件..."
uvx mcp-for-blender@latest install-addon

echo
echo "检测到的 Blender 插件目录："
uvx mcp-for-blender@latest addon-paths || true

cat <<EOF

本机文件安装完成。

接下来：
1. 完全退出并重启 Cursor（macOS 用 Cmd+Q；Windows 从系统托盘退出）。
2. 打开 Blender。
3. Edit → Preferences → Add-ons，搜索并启用 “Interface: MCP for Blender”。
4. 在 3D View 按 N，打开 “MCP for Blender” 页签：
   - 保持端口为 9876；
   - 开启 Poly Haven；
   - 如需 AI 3D 资产，开启 Tripo（或 Meshy / Hunyuan3D / Rodin）；
   - 点击 Start MCP Server。
5. 在 Cursor Settings → MCP 确认项目服务器 “blender” 显示绿色。
6. 在本仓库聊天中发送：
   “使用 Blender MCP 执行 blender_workroom/SMOKE_TEST.md”

项目配置：$ROOT_DIR/.cursor/mcp.json
安全模式：BLENDER_MCP_SAFE_MODE=1
EOF
