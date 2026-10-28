$ErrorActionPreference = "Stop"

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "blender")) {
    Write-Error "未找到 Blender。请先从 https://www.blender.org/download/ 安装 Blender 4.x 或更高版本，并把 blender.exe 加入 PATH。"
}

if (-not (Test-Command "uvx")) {
    if (Test-Command "winget") {
        Write-Host "正在通过 winget 安装 Astral uv..."
        winget install --id Astral-sh.uv -e --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "正在通过 Astral 官方安装器安装 uv..."
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not (Test-Command "uvx")) {
    Write-Error "uvx 安装后仍不可用。请重开 PowerShell，确认 'where.exe uvx' 有输出后重试。"
}

$blenderVersion = (& blender --version | Select-Object -First 1)
Write-Host "Blender: $blenderVersion"
Write-Host "uvx: $((Get-Command uvx).Source)"
Write-Host "正在安装最新版 MCP for Blender 插件..."
& uvx mcp-for-blender@latest install-addon

Write-Host ""
Write-Host "检测到的 Blender 插件目录："
& uvx mcp-for-blender@latest addon-paths

Write-Host @"

本机文件安装完成。

接下来：
1. 从系统托盘完全退出并重启 Cursor。
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

安全模式：BLENDER_MCP_SAFE_MODE=1
"@
