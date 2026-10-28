# 方式二：本机 Cursor Desktop + Blender MCP 实时管线

这套管线让 Cursor Agent 直接控制你本机正在运行的 Blender。它适合实时观察视口、使用本机 GPU
渲染、导入 AI 生成资产，并让 Agent 通过视觉反馈持续修正场景。

## 一、最终架构

```text
Cursor Desktop Agent
        │  MCP stdio
        ▼
uvx mcp-for-blender@latest
        │  TCP 127.0.0.1:9876
        ▼
Blender · MCP for Blender Add-on
        ├─ execute_blender_code  → bpy 建模、材质、灯光、相机、保存
        ├─ look                  → 视口/相机/多角度视觉反馈
        ├─ get_scene_info        → 场景树、变换、材质、拓扑
        ├─ Poly Haven            → CC0 HDRI / PBR / 模型
        └─ generate_3d           → Tripo / Meshy / Hunyuan3D / Rodin
```

项目级 MCP 配置已放在 [`.cursor/mcp.json`](../.cursor/mcp.json)，默认启用：

- `BLENDER_HOST=127.0.0.1`
- `BLENDER_PORT=9876`
- `BLENDER_MCP_SAFE_MODE=1`

安全模式允许正常建模、材质、渲染、保存、导入导出，但会拦截 Blender Python
直接读写任意文件、运行外部程序、联网或安装常驻代码。

## 二、为什么不同时启动独立 `tripo-mcp`

独立的 `Tripo-Developer/tripo-mcp` 和 `mcp-for-blender` 默认都连接 Blender 的
`localhost:9876`，但使用不同的插件协议；同时启用会发生端口占用或命令不兼容。

本项目选择单一 `mcp-for-blender` 桥接，因为它本身已经提供 `generate_3d` 工具，
可在同一 Blender 连接内调用 Tripo、Meshy、Hunyuan3D 或 Rodin，生成后马上继续做
尺寸归一化、原点对齐、法线修复和材质检查。不要再在 Cursor 中启用单独的
`tripo-mcp` 服务器。

## 三、本机安装

### macOS / Linux

```bash
chmod +x scripts/setup_blender_mcp.sh
./scripts/setup_blender_mcp.sh
```

### Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_blender_mcp.ps1
```

脚本会：

1. 检查 Blender；
2. 如有需要，通过 Astral 官方安装器安装 `uv/uvx`；
3. 运行 `uvx mcp-for-blender@latest install-addon`；
4. 打印检测到的 Blender 插件目录和后续手动步骤。

## 四、Blender 侧配置

1. 打开 Blender；
2. `Edit → Preferences → Add-ons`；
3. 搜索并启用 **Interface: MCP for Blender**；
4. 在 3D View 按 `N`，打开 **MCP for Blender** 页签；
5. 保持端口 `9876`；
6. 开启 **Poly Haven**；
7. 需要生成复杂资产时开启 **Tripo**，按插件界面完成账号/API 配置；
8. 点击 **Start MCP Server**。

只运行一个 MCP 客户端。不要让 Cursor 和 Claude Desktop 同时连接同一个 Blender 实例。

## 五、Cursor 侧配置

1. 拉取本分支后，用 Cursor Desktop 打开仓库根目录；
2. 完全退出再重启 Cursor，让它重新读取 `.cursor/mcp.json`；
3. 打开 `Settings → MCP`；
4. 确认 `blender` 显示绿色，并能看到以下工具：
   - `get_addon_status`
   - `execute_blender_code`
   - `look`
   - `get_scene_info`
   - `generate_3d`
5. 如果显示 `spawn uvx ENOENT`：
   - macOS/Linux 运行 `which uvx`；
   - Windows 运行 `where.exe uvx`；
   - 把 `.cursor/mcp.json` 中的 `"command": "uvx"` 改成完整路径；
   - 完全退出并重启 Cursor。

## 六、先跑冒烟测试

不要直接开始复杂书房。先把 [`SMOKE_TEST.md`](SMOKE_TEST.md) 的指令发给 Agent，
确认“执行 → 看图 → 自主纠正 → 另存 `.blend`”完整闭环已连通。

基础测试通过后，再开启 Tripo 做一个复杂资产的付费生成测试。

## 七、正式构建顺序

1. **Stage A · Room Shell**：房间壳体、窗户、主相机；
2. **Stage B · Macro Furniture**：桌、椅、柜、架；
3. **Stage C · Meso Equipment**：显示器、主机、笔记本、灯具；
4. **Stage D · Micro Clutter**：书、杯、纸箱、线缆；
5. **Stage E · Shader & Lighting**：白模验收后再做材质、灯光和体积雾；
6. **Stage F · Camera & Output**：镜头、动画、最终渲染与版本化 `.blend`。

每阶段必须调用 `look` 检查至少一个材质视图和多角度 Solid 视图，不能盲写完整场景后
才第一次渲染。

## 八、常见问题

| 现象 | 处理 |
| --- | --- |
| MCP 服务器红色 / `spawn uvx ENOENT` | 把 `uvx` 改成绝对路径并重启 Cursor |
| `Connection refused 127.0.0.1:9876` | 打开 Blender，在侧栏点击 Start MCP Server |
| 端口已占用 | 退出 Claude Desktop 或另一个 Cursor；只保留一个 MCP 客户端 |
| Tripo 工具不可用 | 在 Blender 插件侧栏开启 Tripo，并用 `get_addon_status` 再检查 |
| Agent 能执行但看不到结果 | 确认 `look` 工具存在；检查 Blender 窗口未卡在模态对话框 |
| 安全模式拦截脚本 | 保持安全模式；让 Agent 改写为纯 `bpy` 操作，不要关闭安全保护 |
| GUI 启动的 Cursor 找不到环境变量 | 凭证优先保存于 Blender Add-on Preferences，不写进仓库 |
