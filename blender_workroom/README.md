# AI Workroom · Blender 自动生成场景

这是 [`docs/ai_blender_workflow.md`](../docs/ai_blender_workflow.md) 的首个可运行实验：
用一支 `bpy` 脚本生成缩小版 AI 书房，包含：

- 房间壳体、木地板与 20 片百叶窗；
- L 型工作台、双显示器、键盘独立按键、PC 主机和笔记本；
- 程序化办公椅、书架、书本、杯子、留言板与曲线线材；
- 日间冷暖混合光、室内体积散射和主镜头；
- 随机色布局图、白模图、最终材质图三套自动诊断渲染。

## 运行

需要 Blender 4.x：

```bash
blender --background --python blender_workroom/build_workroom.py
```

输出位于 `blender_workroom/output/`：

```text
01_layout_random_color.png  # 物体边界、穿模与浮空检查
02_neutral_clay.png         # 几何和基础光影检查
03_daylight_final.png       # 日间材质与体积光预览
ai_workroom.blend           # 可编辑 Blender 工程
```

脚本会先清空当前场景，因此建议在新的 Blender 文件中运行。

## 本机 Cursor Desktop 实时控制

要让 Cursor Agent 直接操作本机 Blender、读取视口并调用 Tripo 等 AI 3D 生成器，
请按 [`LOCAL_MCP_PIPELINE.md`](LOCAL_MCP_PIPELINE.md) 配置。

安装完成后先执行 [`SMOKE_TEST.md`](SMOKE_TEST.md)，确认
“执行 → 视觉检查 → 自主纠正 → 另存 `.blend`”闭环连通，再开始正式场景。
