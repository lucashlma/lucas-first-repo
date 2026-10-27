# AI 全自动控制 Blender 场景构建工作流

**案例来源**：Hirokazu Yokohara（`@Yokohara_h`，东京 CG 工作室 Khaki 联合创始人 / CG 总监）
**目标视频**：[Creating a high-quality Blender scene with AI](https://www.youtube.com/watch?v=kCuoHpv-uZY)（2026 年 10 月）

这份文档拆解 Hirokazu Yokohara 在不手动打开和操作 Blender 的前提下，仅用 **GPT-6 Astra + Claude Opus + 外部 3D 生成器** 完成高细节室内书房场景（从建模、陈设、程序化材质、体积雾灯光、镜头合成，一路到自动移植进 UE5 实时运行）的完整工作流，并给出在本地或 Agent 环境中落地的实操方案。

---

## 一、视频与项目背景：究竟做了什么

这个项目的核心限制条件只有一条：**人类创作者自己一次都不碰 Blender 界面**（"without ever directly operating Blender myself"），所有建模、摆放、材质、打光、合成、运镜均由 AI Agent 通过脚本（`bpy`）和工具链（MCP / CLI）执行，人类只负责下达自然语言指令和阶段性看图给反馈。

整个实验分四个阶段推进（时间均换算为香港时间 UTC+8）：

| 阶段 | 发布时间（UTC+8） | 载体 | 核心内容与突破 |
| --- | --- | --- | --- |
| 1. 夜间版 WIP | 2026-10-09 23:30 | X 原生视频（25.7s） | 首次跑通「完全不碰 Blender、连建模也全靠 AI」的杂乱书房夜景；验证混合建模路由与 Blender Solid Random Color 视口分割检验 |
| 2. 日间版 | 2026-10-13 20:28 | X / LinkedIn 视频（28.4s） | 补齐房间另一侧细节；完全交由 AI 把夜景改为百叶窗日间透光 + 体积雾（Volumetric Fog）+ 合成（Compositing） |
| 3. YouTube 完整拆解 | 2026-10-15 01:46 | YouTube `kCuoHpv-uZY` | 汇总完整工作流步骤：AI 主导资产路由（Wireframe）、分层级房间陈设（Dressing the Room）、AI 编写 Shader 节点（Neutral Surfaces → Final） |
| 4. UE5 实时版移植 | 2026-10-16 | X / LinkedIn 视频（47s） | 用 Claude Opus 把整套 Blender 场景自动移植进 Unreal Engine 5（Lumen + Post-Process），完成材质烘焙转换与实时漫游 |

---

## 二、核心工具栈与雙模型分工（Astra + Opus）

缩略图左上角明确标出了工具组合：**Made with Blender + OpenAI（GPT-6 Astra）+ Anthropic（Claude Opus）**，外加图像生成与 Image-to-3D 生成工具。

为什么同时用两个大模型，而不是单跑一个？根据作者在推文及评论区的原话（*"Astra was used, with guidance from Opus"*），两者的职责边界非常清晰：

| 角色 | 工具 / 模型 | 在管线里干什么 |
| --- | --- | --- |
| **总控与架构指导（Planner / Critic / Porting）** | **Claude Opus** | 1. 拆解任务、规划场景层级与资产清单；<br>2. 指导 Astra 的建模与场景修正方向；<br>3. 负责跨 DCC 的重度工程迁移（如把 Blender 场景、PBR 与程序化材质自动转换并导入 UE5）。 |
| **Blender 执行与空间构建（Executor / Spatial Builder）** | **GPT-6 Astra**（Codex 环境） | 1. 直接编写并执行 Blender Python（`bpy`）脚本；<br>2. 程序化硬表面建模、修改器堆栈与网格修整；<br>3. 编写材质节点树、布置灯光、体积雾、摄像机动画并调用 Cycles 渲染预览。 |
| **高复杂度有机/日用资产生成** | **图像生成 → 3D 生成工具**（如 Tripo / Meshy 等 MCP 服务） | 针对难以用纯 `bpy` 代码写出来的复杂曲面或软包家具，先生成参考图，再转成 3D 基础网格导回 Blender。 |
| **宿主与渲染引擎** | **Blender（Cycles）→ UE5（Lumen）** | Blender 负责通过 `bpy` 接收控制并完成离线渲染；UE5 作为下游实时引擎接收导出的 FBX、贴图与 JSON 场景描述。 |
| **人类（Director）** | 创作者本人（甚至只用手机 + 语音输入） | 不碰三维软件；定期看 AI 渲染出的预览图，重点针对**物体空间摆放（Layout）**给出纠偏指令。 |

---

## 三、五步核心工作流拆解（对应视频章节）

视频通过线框（Wireframe）、白模（Neutral Surfaces）、随机色块视口（Random Color Solid）和最终渲染（Cycles Render）四套视图，展示了整套流水线的五个阶段：

```text
[自然语言需求 / 空间设定]
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段 1：AI 主导的混合资产路由 (AI-Directed Asset Creation)   │
│ AI 逐物体判断：                                              │
│   ├─ 路径 A：规则几何/硬表面 ──► 直接写 bpy 脚本建模         │
│   └─ 路径 B：复杂曲面/有机体 ──► 生图 → 3D 生成 → Blender 修整│
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段 2：由大到小的层级化陈设 (Dressing the Room)             │
│ 白模房间壳体 ──► 大件家具 ──► 中型设备 ──► 桌面杂物与电线    │
│ （此阶段人类反馈最密集，通过渲染图 + 随机色视口反复纠偏）    │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段 3：AI 编写程序化材质节点 (AI-Authored Shaders)          │
│ 从 Neutral Surfaces 白模出发，写 bpy 脚本构建 Shader 节点：  │
│ 表面磨损 (Surface Wear)、玻璃折射、屏幕自发光、木纹与塑料    │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段 4：灯光、体积雾与镜头合成 (Lighting, Fog & Camera)       │
│ 夜间台灯/屏幕光 ──► 日间百叶窗透光 + Volumetric Scattering   │
│ Blender 合成器节点 + 312 帧（24fps）手持感推进镜头           │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 阶段 5：跨引擎自动移植 (Blender → Unreal Engine 5)           │
│ Opus 驱动：已有 PBR 原样迁移；Blender 专属节点烘焙 Mask      │
│ 并在 UE5 中用原生 Shader 重建，配合 Lumen 实现实时可漫游场景 │
└─────────────────────────────────────────────────────────────┘
```

### 阶段 1：AI 主导的混合资产路由（AI-Directed Asset Creation）

> 视频字幕卡：**"AI-Directed Asset Creation — AI decided which assets to model directly, which to generate, and which needed refinement. [WIREFRAME]"**

这是整套流程能兼顾「全AI生成」与「高画质」的最关键设计。如果所有物体都让 LLM 写 `bpy` 顶点/布尔代码，人体工学椅的软包、怪兽手办、揉皱的纸团会非常假；反过来，如果所有物体都走 3D 生成（Image-to-3D），书架、百叶窗、显示器边框又会出现网格歪斜、直角不直的问题。

Yokohara 的做法是**把选择权交给 AI Agent 自己路由**：

1. **路径 A：直接 `bpy` 脚本建模（Direct Modeling）**
   - **适用对象**：建筑壳体（墙壁、木地板、窗户、百叶窗）、规则家具（L 型书桌、木质书柜、金属置物架、抽屉柜）、硬表面电子设备（双显示器、键盘、PC 机箱、笔记本电脑、台灯）以及散乱线材（Bezier Curve + Bevel Depth）。
   - **细节特征**：连主显示器画面里显示的「Blender 软件界面」、键盘上的独立按键、百叶窗叶片都是实打实的几何体/贴图结构。
2. **路径 B：图像生成 → 3D 生成 → Blender 后处理（Generate & Refine）**
   - **适用对象**：黑色皮质人体工学转椅（带软垫褶皱与五爪滚轮）、立式无线吸尘器、机箱顶部的哥斯拉（Godzilla）怪兽手办与机器人模型、抽屉把手上的卡比兽小摆件、地上软质蓝色手提包、垃圾桶里的废纸等。
   - **Blender 内修整（Refinement）**：3D 生成器导出的 `.glb`/`.fbx` 往往存在原点偏移、尺寸不对、法线破碎或底面不平。AI 会在导入后用 `bpy` 脚本自动重算边界框（Bounding Box）、对齐底部 Z=0、清理破面、重算法线并调整材质槽。

### 阶段 2：由大到小的层级化场景陈设（Dressing the Room）

> 视频字幕卡：**"Dressing the Room — Large props arrive first, followed by smaller objects to build up the finished layout."**

从日间版视频的后半段（第 19s–27s 的延时生长拆解）和夜间版的 Blender 视口截图，可以完整看到 AI 搭建房间的四个空间层级：

1. **Level 0 · 建筑壳体（Block-out，19s–20s）**：先建立房间墙体、地面、窗户开口和百叶窗结构。
2. **Level 1 · 大件骨干家具（Macro Props，21s–22s）**：放入主书桌、右侧金属抽屉柜、左右两侧木质书柜、白色金属网格架，随后将主视觉焦点——黑色皮质办公椅归位。
3. **Level 2 · 中型功能设备（Meso Props，23s）**：在书桌支撑面上放置双联显示器、摄像头、PC 主机、笔记本电脑、扫描仪、夹式长臂台灯、立式吸尘器、墙角空调与地面收纳箱。
4. **Level 3 · 微观生活杂物（Micro Clutter，24s–27s）**：往桌面、书架隔板和地面填充高密度的生活痕迹——马克杯、水杯、药瓶/眼药水、游戏手柄、成摞的书籍与文件、印有 `UNIT-04` 的纸箱、软木留言板上的图纸、散落的笔、满溢的废纸篓，以及桌面上盘根错节的黑色电源线/数据线。

**为什么 Layout（摆放）是最难的一步？**
作者在 LinkedIn 和 X 上多次强调：*"Layout was the most challenging part"*、*"配置含めすべてAIです！ただし配置に関しては結構修正指示出しました"*（包括摆放在内全是 AI 做的，但在摆放上我给了相当多的修改指令）。
LLM 在三维空间中很容易出现穿模（Intersection）、悬空（Floating）、朝向反人类的情况。为此：
- 视口切换到 **Solid + Random Color（按物体随机赋色）** 模式：让每个独立物体呈现高对比度的纯色（紫、薄荷绿、天蓝等），方便 AI 的多模态视觉（或人类审核）一眼看清物体边界、穿模与堆叠关系；
- 视口采样设为 `Max Samples: 128`（开启降噪），而快速预览渲染采样压到极低的 `Max Samples: 12`，用于高频跑出构图预览图供迭代。

### 阶段 3：AI 编写程序化材质节点（AI-Authored Shaders）

> 视频字幕卡：**"AI-Authored Shaders — AI wrote Blender scripts to build and refine material nodes, surface wear and glass shaders. [NEUTRAL SURFACES]"**

模型摆好后，全场景先以统一的哑光灰白模（Neutral Surfaces / Clay Render）做几何与光影基线检验；随后 AI 通过 `bpy.data.materials` 编写完整的 Shader 节点树：

- **程序化表面磨损（Surface Wear）**：利用噪波（Noise / Musgrave / Voronoi）、环境光遮蔽（Ambient Occlusion）或几何节点属性（Pointiness / Edge Wear）驱动 Roughness 与 Base Color 的微变化，让皮椅、桌面、纸箱和塑料外壳摆脱 CG 塑料感；
- **玻璃与半透明材质（Glass & Translucency）**：桌面上的水杯、红茶杯、药瓶、收纳盒以及窗户百叶窗的半透光漫射；
- **自发光与屏幕细节（Emissive Surfaces）**：右侧显示器点亮并贴上真实的 Blender 工作界面截图，左侧显示器保持息屏黑玻璃反射，形成强烈的冷暖与明暗对比。

### 阶段 4：灯光、体积雾与运镜合成（Lighting, Fog, Compositing & Camera）

这是最让作者本人惊讶的环节。他在推文中评价：
> *"ライティングとコンポジットとカメラワークはフィードバックほぼ無しでいい感じまで出来た。ボリュームフォグの追加はAIのほうが自分より速くて上手いかも"*
> （灯光、合成和运镜几乎没怎么给反馈就做到了很好的效果。添加体积雾这件事，AI 可能比我自己做还要快、还要好。）

1. **两套灯光环境无缝切换**：
   - **夜间版（Oct 9）**：以主显示器屏幕冷光 + 左侧长臂台灯暖光为主光源，背景百叶窗外隐约透出城市夜景微光，营造深夜加班的局部高反差氛围；
   - **日间版（Oct 13）**：完全交给 AI 改造成白天。窗外强日光穿过水平百叶窗，在室内空气中拉出柔和的丁达尔体积光束（Volumetric Scattering / Fog），同时自动调整室内漫反射曝光与暗部补光。
2. **镜头运动（Camera Work）**：
   - 工程时间轴共 **312 帧**（24 fps，约 13 秒一段主镜头，剪辑合成为 26–28 秒视频）；
   - AI 用脚本为摄像机加上了带呼吸感与微小晃动的手持推进/横移轨迹（Camera Shake / Noise Modifier），模拟真人拿着相机在狭窄杂乱的书房里环视的效果（也正因为这种逼真的手持运镜 + 体积雾，评论区不少人误以为是实拍视频转 NeRF 或视频生成模型跑出来的）。
3. **Blender 合成器（Compositor）**：
   - AI 自动在 Blender Compositor 中串接辉光（Glare / Fog Glow）、镜头畸变/色散（Lens Distortion）、暗角与色调映射，直接从 Blender 产出最终成片感。

### 阶段 5：自动移植到 Unreal Engine 5（Blender → UE5 实时化）

10 月 13 日完成日间版后，作者提出下一步是转入 UE5；10 月 16 日即放出了 47 秒的 UE5 实时漫游版本，并公开了 **Claude Opus 自动跨引擎移植**的技术细节：

- **双轨材质转换策略**（作者回复 `@arpeegee` 原话）：
  1. **标准 PBR 材质**：指示 Opus 将已有的贴图型 PBR 材质原样（as-is）转换并连入 UE5 材质球；
  2. **Blender 程序化节点材质**：Blender 独有的 Shader 节点（如复杂的程序化磨损、混色）无法直接导出 FBX。作者指示 Opus **只把最核心的程序化通道（如磨损遮罩 Masks）在 Blender 里烘焙（Bake）成贴图**，其余材质逻辑则在 UE5 里调用 Unreal 原生 Shader 节点重新搭建。
- **光照与后处理对齐**：
  - 在 UE5 中开启 **Lumen** 全局光照与反射 + **Post-Process Volume**，还原 Blender Cycles 里的显示器自发光（Emissive Texture）与百叶窗日间体积雾氛围，使场景变成可直接拿来做小型恐怖/探索游戏的实时关卡。

---

## 四、这套工作流的运作模式与成本特征

从作者在 X 和 LinkedIn 上的复盘，可以提炼出这套「AI 托管式 CG 工作流」的几个真实工程特征：

1. **挂机式长时迭代（Long-running Agent Loop）**：
   - 作者坦言：*"これ大したことはやらせてなくて地道なこと延々コツコツやらせただけではある。codexのリセットが大量に溜まってるから3日間くらい作業させてた"*（其实没让它干什么玄乎的事，就是让它把枯燥扎实的工作没日没夜地一点点磨出来。因为攒了很多 Codex 额度重置，就让它连续跑了大概 3 天）。
   - 后续测试「无限循环房间」时，也是在**睡觉时间让 AI 后台持续跑构建和修正**。
2. **移动端 + 语音的「导演式」交互**：
   - 房间另一侧的细节扩充和日间灯光改造，是作者在休假日**只用一部手机 + 语音输入**远程指挥完成的：*"画面小さいこと以外は特に問題なかった。音声入力があるからキーボードも必須ではなくなってきた"*（除了屏幕小一点之外完全没问题，因为有语音输入，连键盘都不是必需品了）。
3. **人类经验的价值体现在「审美把关与拆解指令」**：
   - 虽然全程没碰 Blender，但作者有 15 年 CG 总监经验（Khaki 联合创始人）。他知道什么时候该让 AI 看线框、什么时候看白模、哪类材质去 UE5 必须先 Bake Mask，以及在 Layout 穿模时如何用精确的空间语言纠正 AI。

---

## 五、实操落地指南：如何搭建同款 AI 控制 Blender 环境

如果你想在自己的机器或 Cursor / Claude / Codex 环境中复现这套「AI 全权控制 Blender + 3D 生成」的工作流，按以下四步配置即可。

### 1. 基础架构：两条连接通道

AI 控制 Blender 有两种互补方式（Yokohara 的工作流兼具两者）：

| 通道 | 原理 | 适合干什么 |
| --- | --- | --- |
| **通道 A：CLI 批处理模式** | Agent 直接在终端运行 `blender -b scene.blend -P script.py` | 适合 Codex / Cursor Agent 在后台无人值守地跑大批量建模、烘焙贴图、离线渲染序列帧。 |
| **通道 B：实时 MCP Socket 桥接** | 在 Blender 内装一个轻量插件开启本地 Socket，MCP Server 把工具暴露给 LLM | 适合边看视口边交互、实时查询场景树（Outliner）、调用外部 3D 生成 API（Tripo / Poly Haven / Hyper3D）。 |

### 2. 配置 MCP Server（Blender + 3D 生成）

在 Cursor（`.cursor/mcp.json`）或 Claude Code 中挂载 `blender-mcp` 与 `tripo-mcp`（当前环境已预置这两个命名空间）：

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": ["blender-mcp"]
    },
    "tripo-mcp": {
      "command": "uvx",
      "args": ["tripo-mcp"],
      "env": {
        "TRIPO_API_KEY": "your_tripo_api_key"
      }
    }
  }
}
```

### 3. 核心验证闭环脚本（Agent 自检用的四视图渲染器）

不碰 Blender 的核心前提是：**AI 必须能「看见」自己改出来的东西**。不能只让 AI 盲写 `bpy` 代码，必须要求它每完成一个阶段就输出以下四种诊断图并调用多模态视觉自检：

1. **Random Color Solid（物体分割与穿模检查）**——对应夜间版视频第 8s–17s 的彩色视口；
2. **Wireframe（拓扑密度与网格检查）**——对应视频 `AI-Directed Asset Creation` 章节；
3. **Neutral Clay（白模几何与光影检查）**——对应视频 `AI-Authored Shaders` 章节；
4. **Low-Sample Cycles Preview（12~32 采样快速材质灯光预览）**。

下面这段 `bpy` 诊断脚本可以直接交给 Agent 在每次修改后调用：

```python
import bpy
from pathlib import Path


def render_diagnostic_views(out_dir: str, preview_samples: int = 16) -> None:
    """输出与视频同款的三套诊断图（随机色分割、白模、低采样 Cycles 预览）。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene

    # 1. Workbench 随机色（检查穿模、浮空、物体边界）
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "RANDOM"
    scene.display.shading.show_cavity = True
    scene.render.filepath = str(out / "01_layout_random_color.png")
    bpy.ops.render.render(write_still=True)

    # 2. Clay 白模（检查几何形体与基础光影，排除贴图干扰）
    scene.render.engine = "CYCLES"
    scene.cycles.samples = preview_samples
    scene.cycles.use_denoising = True
    clay_mat = bpy.data.materials.get("_Diagnostic_Clay") or bpy.data.materials.new("_Diagnostic_Clay")
    clay_mat.use_nodes = True
    scene.view_layers[0].material_override = clay_mat
    scene.render.filepath = str(out / "02_neutral_clay.png")
    bpy.ops.render.render(write_still=True)
    scene.view_layers[0].material_override = None

    # 3. Cycles 材质与体积雾快速预览
    scene.cycles.samples = preview_samples
    scene.render.filepath = str(out / "03_cycles_preview.png")
    bpy.ops.render.render(write_still=True)
```

### 4. 复现该工作流的 System Prompt 模板

将以下工作流规范放进项目的 `CLAUDE.md` 或 `.cursor/rules/blender-workflow.mdc`，即可让 Agent 按 Yokohara 的混合管线运作：

```markdown
# AI-Only Blender Scene Production Workflow

你是一个全自动控制 Blender 的 3D 场景构建 Agent。人类不会手动打开 Blender，所有操作必须由你通过 `bpy` 脚本或 MCP 工具完成。

## 1. 资产路由原则（AI-Directed Asset Creation）
拿到场景需求后，先把所有物体拆解为资产清单，并按以下规则自动路由：
- **直接 `bpy` 建模**：房间壳体、门窗百叶窗、桌子、书架、柜子、显示器、键盘、机箱、灯具、书本、杯子、线缆（Curve）。
- **图像生成 → 3D 生成 → `bpy` 修整**：带褶皱的软包办公椅、复杂电器（如吸尘器）、角色/怪兽手办、软质背包、不规则杂物。导入生成的 `.glb`/`.fbx` 后，必须用脚本执行：
  1. 归一化尺寸至真实物理尺度（米）；
  2. 将底部原点对齐到支撑面（`z_min = 0`）；
  3. 开启 Auto Smooth / Weighted Normal 修复着色。

## 2. 层级化陈设（Dressing the Room）
严格按四个阶段推进，每阶段必须渲染 `01_layout_random_color.png` 自检通过后再进入下一阶段：
1. **Stage A（Room Shell）**：墙体、地面、窗户开口、主摄像机机位；
2. **Stage B（Macro Furniture）**：桌、椅、柜、架等大件家具，确认动线与比例；
3. **Stage C（Meso Equipment）**：显示器、主机、笔记本、台灯、电器；
4. **Stage D（Micro Clutter & Cables）**：书籍堆叠、杯子、药瓶、纸箱、废纸篓、桌面曲线线缆，消除「CG 样板间」的空旷感。

## 3. 程序化材质与灯光（Shaders, Lighting & Volumetric Fog）
- 先输出 `02_neutral_clay.png` 白模图确认几何无误；
- 用 `bpy` 节点构建材质：为硬表面加入基于 Noise/AO 的粗糙度微变化（Surface Wear），为显示器屏幕配置 Emissive 贴图，为玻璃器皿配置透射 shader；
- 使用体积散射（Principled Volume）包裹室内空间，配合窗外高强度 Sun / Area Light 穿过百叶窗产生自然丁达尔光束；
- 在 Blender Compositor 中配置 Glare（Fog Glow）与色彩校正。

## 4. 跨引擎导出（Blender → UE5，可选）
- 导出前记录完整场景的 JSON 描述文件（物体变换矩阵、主从层级、灯光参数）；
- 标准 PBR 材质直接导出贴图；
- 含 Blender 专属程序化节点的材质，先用 Cycles Bake 将关键遮罩（Wear/Dirt Mask）烘焙为贴图，再在 UE5 中用原生材质节点重建。
```

---

## 六、和本仓库现有工具（`sky_to_hdr.py`）的衔接点

如果你也按 Yokohara 的路线走 **「Blender 场景构建 → 导入 UE5 实时渲染」**，环境光是跨引擎时最容易失真的一环：

1. 在阶段 4（日间灯光设计）或阶段 5（移植 UE5）时，如果需要把 AI 生成的 2:1 天空全景图（或 Blender 渲染出的环境背景图）带进 UE5 的 `SkyLight` / `HDRI Backdrop`；
2. 可以直接调用本仓库的 [`sky_to_hdr.py`](../sky_to_hdr.py) 把它转成符合 UE 解析规范的 Radiance `.hdr`（自动补齐被 8-bit 削顶的太阳盘能量，并算出 UE 平行光的 `Pitch` / `Yaw`），具体参数参见 [`docs/sky_to_hdr_ue.md`](sky_to_hdr_ue.md)。
